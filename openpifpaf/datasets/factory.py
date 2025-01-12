import torch

from .coco import Coco
from .keemotion import Keemotion
from .deepsport import DeepSportDataset
from .deepsport import build_DeepSportBall_datasets
from .collate import collate_images_targets_meta
from .collate import collate_images_targets_inst_meta
from .constants import COCO_KEYPOINTS, HFLIP, COCO_CATEGORIES
from .. import transforms

from .multidataset import MultiDataset



COCOKP_ANNOTATIONS_TRAIN = 'COCO/annotations/person_keypoints_train2017.json'
COCOKP_ANNOTATIONS_VAL = 'COCO/annotations/person_keypoints_val2017.json'
COCODET_ANNOTATIONS_TRAIN = 'COCO/annotations/instances_train2017.json'
COCODET_ANNOTATIONS_VAL = 'COCO/annotations/instances_val2017.json'
COCO_IMAGE_DIR_TRAIN = 'COCO/images/train2017/'
COCO_IMAGE_DIR_VAL = 'COCO/images/val2017/'
# KEEMOTION_DIR = '/scratch/mistasse/keemotion/km_complete_player_ball_full_res/'



def train_cli(parser):
    group = parser.add_argument_group('dataset and loader')
    group.add_argument('--cocokp-train-annotations', default=COCOKP_ANNOTATIONS_TRAIN)
    group.add_argument('--cocodet-train-annotations', default=COCODET_ANNOTATIONS_TRAIN)
    group.add_argument('--cocoinst-train-annotations', default=COCODET_ANNOTATIONS_TRAIN)
    group.add_argument('--cocokp-val-annotations', default=COCOKP_ANNOTATIONS_VAL)
    group.add_argument('--cocodet-val-annotations', default=COCODET_ANNOTATIONS_VAL)
    group.add_argument('--cocoinst-val-annotations', default=COCODET_ANNOTATIONS_VAL)
    group.add_argument('--coco-train-image-dir', default=COCO_IMAGE_DIR_TRAIN)
    group.add_argument('--coco-val-image-dir', default=COCO_IMAGE_DIR_VAL)
    group.add_argument('--keemotion-dir', default=KEEMOTION_DIR)
    group.add_argument('--deepsport-pickled-dataset', default=None)
    group.add_argument('--dataset', default='cocokpinst')
    group.add_argument('--n-images', default=None, type=int,
                       help='number of images to sample')
    group.add_argument('--duplicate-data', default=None, type=int,
                       help='duplicate data')
    group.add_argument('--loader-workers', default=None, type=int,
                       help='number of workers for data loading')
    group.add_argument('--batch-size', default=8, type=int,
                       help='batch size')

    group_aug = parser.add_argument_group('augmentations')
    group_aug.add_argument('--square-edge', default=385, type=int,
                           help='square edge of input images')
    group_aug.add_argument('--extended-scale', default=False, action='store_true',
                           help='augment with an extended scale range')
    group_aug.add_argument('--orientation-invariant', default=0.0, type=float,
                           help='augment with random orientations')
    group_aug.add_argument('--no-augmentation', dest='augmentation',
                           default=True, action='store_false',
                           help='do not apply data augmentation')

    group.add_argument('--dataset-weights', default=None, nargs='+', type=float,
                       help='n-1 weights for the datasets')

    group.add_argument('--focus-object', default=None,
                        help='player or ball or None')
    group.add_argument('--dataset-fold', default=None)

    group.add_argument('--filter-for-medium-coco', default=False, action='store_true')

    group.add_argument('--debug-on-testset', default=False, action='store_true')

def train_configure(args):
    pass


def train_cocokp_preprocess_factory(
        *,
        square_edge,
        augmentation=True,
        extended_scale=False,
        orientation_invariant=0.0,
        rescale_images=1.0,
        heads=None,
    ):
    if not augmentation:
        return transforms.Compose([
            transforms.NormalizeAnnotations(),
            transforms.RescaleAbsolute(square_edge),
            transforms.CenterPad(square_edge),
            transforms.EVAL_TRANSFORM,
        ])

    # if extended_scale:
    #     rescale_t = transforms.RescaleRelative(
    #         scale_range=(1 * rescale_images, 1 * rescale_images),
    #         power_law=True)
    # else:
    #     rescale_t = transforms.RescaleRelative(
    #         scale_range=(1 * rescale_images, 1 * rescale_images),
    #         power_law=True)

    if extended_scale:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.25 * rescale_images, 2.0 * rescale_images),
            power_law=True)
    else:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.4 * rescale_images, 2.0 * rescale_images),
            power_law=True)

    orientation_t = None
    if orientation_invariant:
        orientation_t = transforms.RandomApply(transforms.RotateBy90(), orientation_invariant)

    BALL_KP_IDX = 18
    CENTER_KP_IDX = 17
    BODY_KPS = slice(0, 17)
    coco_keypoints_ = COCO_KEYPOINTS[BODY_KPS]
    if 'cifball' in heads:
        coco_keypoints_ = COCO_KEYPOINTS[BODY_KPS] + [COCO_KEYPOINTS[BALL_KP_IDX]]
    elif 'cifcentball' in heads:
        coco_keypoints_ = COCO_KEYPOINTS
    elif 'cifcent' in heads:
        coco_keypoints_ = COCO_KEYPOINTS[BODY_KPS] + [COCO_KEYPOINTS[CENTER_KP_IDX]]
    elif False:#'ball' in heads:
        coco_keypoints_ = [COCO_KEYPOINTS[BALL_KP_IDX]]

    return transforms.Compose([
        transforms.NormalizeAnnotations(),
        transforms.AnnotationJitter(),
        transforms.RandomApply(transforms.HFlip(coco_keypoints_, HFLIP), 0.5),
        # rescale_t,
        # transforms.Crop(square_edge, use_area_of_interest=False),
        # transforms.CenterPad(square_edge),
        # orientation_t,
        transforms.TRAIN_TRANSFORM,
    ])


def train_cocodet_preprocess_factory(
        *,
        square_edge,
        augmentation=True,
        extended_scale=False,
        orientation_invariant=0.0,
        rescale_images=1.0,
    ):
    if not augmentation:
        return transforms.Compose([
            transforms.NormalizeAnnotations(),
            transforms.RescaleAbsolute(square_edge),
            transforms.CenterPad(square_edge),
            transforms.EVAL_TRANSFORM,
        ])

    if extended_scale:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.5 * rescale_images, 2.0 * rescale_images),
            power_law=True)
    else:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.7 * rescale_images, 1.5 * rescale_images),
            power_law=True)

    orientation_t = None
    if orientation_invariant:
        orientation_t = transforms.RandomApply(transforms.RotateBy90(), orientation_invariant)

    return transforms.Compose([
        transforms.NormalizeAnnotations(),
        transforms.AnnotationJitter(),
        transforms.RandomApply(transforms.HFlip(COCO_KEYPOINTS, HFLIP), 0.5),
        rescale_t,
        transforms.Crop(square_edge, use_area_of_interest=False),
        transforms.CenterPad(square_edge),
        orientation_t,
        transforms.MinSize(min_side=4.0),
        transforms.UnclippedArea(),
        transforms.UnclippedSides(),
        transforms.TRAIN_TRANSFORM,
    ])



### AMA

def train_cocokpinst_preprocess_factory(
        *,
        square_edge,
        args,
        augmentation=False,
        extended_scale=False,
        orientation_invariant=0.0,
        rescale_images=1.0,
        heads=None,
        ):
    if not augmentation:
        return transforms.Compose([
            transforms.NormalizeAnnotations(),
            transforms.RescaleAbsolute(square_edge),
            transforms.CenterPad(square_edge),
            transforms.EVAL_TRANSFORM,
        ])

    if extended_scale:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.25 * rescale_images, 2.0 * rescale_images),
            power_law=True)
    else:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.4 * rescale_images, 2.0 * rescale_images),
            power_law=True)

    orientation_t = None
    if orientation_invariant:
        orientation_t = transforms.RandomApply(transforms.RotateBy90(), orientation_invariant)

    print("heads:", heads)
    coco_keypoints_ = COCO_KEYPOINTS[:17]
    if 'cifball' in heads:
        coco_keypoints_ = COCO_KEYPOINTS[:17] + [COCO_KEYPOINTS[-1]]
    elif 'cifcentball' in heads:
        coco_keypoints_ = COCO_KEYPOINTS
    elif 'cifcent' in heads:
        print('yeay')
        coco_keypoints_ = COCO_KEYPOINTS[:18]
    # elif 'ball' in heads:
    #     coco_keypoints_

    return transforms.Compose([
        transforms.NormalizeAnnotations(),
        transforms.AnnotationJitter(),
        transforms.RandomApply(transforms.HFlip(coco_keypoints_, HFLIP), 0.5),
        rescale_t,
        transforms.Crop(square_edge, use_area_of_interest=True),
        transforms.CenterPad(square_edge),
        orientation_t,
        transforms.TRAIN_TRANSFORM,
    ])

def train_keemotion_preprocess_factory(
        *,
        square_edge,
        args,
        augmentation=False,
        extended_scale=False,
        orientation_invariant=0.0,
        rescale_images=1.0,
        heads=None,
        ):
    if not augmentation:
        return transforms.Compose([
            transforms.NormalizeAnnotations(),
            transforms.ZoomScale(),
            transforms.RescaleAbsolute(square_edge),
            transforms.CenterPad(square_edge),
            transforms.EVAL_TRANSFORM,
        ])

    if extended_scale:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.25 * rescale_images, 2.0 * rescale_images),
            power_law=True)
    else:
        rescale_t = transforms.RescaleRelative(
            scale_range=(0.4 * rescale_images, 2.0 * rescale_images),
            power_law=True)

    orientation_t = None
    if orientation_invariant:
        orientation_t = transforms.RandomApply(transforms.RotateBy90(), orientation_invariant)

    print("heads2:", heads)
    coco_keypoints_ = COCO_KEYPOINTS[:17]
    if 'cifball' in heads:
        coco_keypoints_ = COCO_KEYPOINTS[:17] + [COCO_KEYPOINTS[-1]]
    elif 'cifcentball' in heads:
        coco_keypoints_ = COCO_KEYPOINTS
    elif 'cifcent' in heads:
        print('yeay')
        coco_keypoints_ = COCO_KEYPOINTS[:18]

    return transforms.Compose([
        transforms.NormalizeAnnotations(),
        transforms.AnnotationJitter(),
        transforms.ZoomScale(),
        transforms.RandomApply(transforms.HFlip(coco_keypoints_, HFLIP), 0.5),
        rescale_t,
        transforms.CropKeemotion(square_edge, use_area_of_interest=True),
        transforms.CenterPad(square_edge),
        orientation_t,
        transforms.TRAIN_TRANSFORM,
    ])

def train_deepsport_factory(args, target_transforms, heads=None, batch_size=None):
    if args.loader_workers is None:
        args.loader_workers = 0

    preprocess = train_cocokp_preprocess_factory(
        square_edge=args.square_edge,
        augmentation=args.augmentation,
        extended_scale=args.extended_scale,
        orientation_invariant=args.orientation_invariant,
        rescale_images=args.rescale_images,
        heads=heads)


    train_data, val_data = build_DeepSportBall_datasets(
        pickled_dataset_filename=args.deepsport_pickled_dataset,
        validation_set_size_pc=15, square_edge=args.square_edge, target_transforms=target_transforms, preprocess=preprocess, focus_object=args.focus_object, config=heads, dataset_fold=args.dataset_fold, debug_on_test=args.debug_on_testset)

    train_loader = torch.utils.data.DataLoader(
        train_data, batch_size=batch_size, shuffle=not args.debug,
        pin_memory=args.pin_memory, num_workers=0, drop_last=True,
        collate_fn=collate_images_targets_inst_meta,)

    val_loader = torch.utils.data.DataLoader(
        val_data, batch_size=batch_size, shuffle=False,
        pin_memory=args.pin_memory, num_workers=0, drop_last=True,
        collate_fn=collate_images_targets_inst_meta,)

    return train_loader, val_loader




def train_cocokp_factory(args, target_transforms):
    preprocess = train_cocokp_preprocess_factory(
        square_edge=args.square_edge,
        augmentation=args.augmentation,
        extended_scale=args.extended_scale,
        orientation_invariant=args.orientation_invariant,
        rescale_images=args.rescale_images)

    if args.loader_workers is None:
        args.loader_workers = args.batch_size

    train_data = Coco(
        image_dir=args.coco_train_image_dir,
        ann_file=args.cocokp_train_annotations,
        preprocess=preprocess,
        target_transforms=target_transforms,
        n_images=args.n_images,
        image_filter='keypoint-annotations',
        category_ids=[1],
    )
    if args.duplicate_data:
        train_data = torch.utils.data.ConcatDataset(
            [train_data for _ in range(args.duplicate_data)])
    train_loader = torch.utils.data.DataLoader(
        train_data, batch_size=args.batch_size, shuffle=not args.debug,
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_meta)

    val_data = Coco(
        image_dir=args.coco_val_image_dir,
        ann_file=args.cocokp_val_annotations,
        preprocess=preprocess,
        target_transforms=target_transforms,
        n_images=args.n_images,
        image_filter='keypoint-annotations',
        category_ids=[1],
    )
    if args.duplicate_data:
        val_data = torch.utils.data.ConcatDataset(
            [val_data for _ in range(args.duplicate_data)])
    val_loader = torch.utils.data.DataLoader(
        val_data, batch_size=args.batch_size, shuffle=False,
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_meta)

    return train_loader, val_loader


def train_cocodet_factory(args, target_transforms):
    preprocess = train_cocodet_preprocess_factory(
        square_edge=args.square_edge,
        augmentation=args.augmentation,
        extended_scale=args.extended_scale,
        orientation_invariant=args.orientation_invariant,
        rescale_images=args.rescale_images)

    if args.loader_workers is None:
        args.loader_workers = args.batch_size

    train_data = Coco(
        image_dir=args.coco_train_image_dir,
        ann_file=args.cocodet_train_annotations,
        ann_inst_file=None,
        preprocess=preprocess,
        target_transforms=target_transforms,
        n_images=args.n_images,
        image_filter='annotated',
        category_ids=[37],  ## sports ball
    )
    if args.duplicate_data:
        train_data = torch.utils.data.ConcatDataset(
            [train_data for _ in range(args.duplicate_data)])
    train_loader = torch.utils.data.DataLoader(
        train_data, batch_size=args.batch_size, shuffle=False,
        sampler=torch.utils.data.WeightedRandomSampler(
            train_data.class_aware_sample_weights(), len(train_data), replacement=True),
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_meta)

    val_data = Coco(
        image_dir=args.coco_val_image_dir,
        ann_file=args.cocodet_val_annotations,
        preprocess=preprocess,
        target_transforms=target_transforms,
        n_images=args.n_images,
        image_filter='annotated',
        category_ids=[],
    )
    if args.duplicate_data:
        val_data = torch.utils.data.ConcatDataset(
            [val_data for _ in range(args.duplicate_data)])
    val_loader = torch.utils.data.DataLoader(
        val_data, batch_size=args.batch_size, shuffle=False,
        sampler=torch.utils.data.WeightedRandomSampler(
            val_data.class_aware_sample_weights(), len(val_data), replacement=True),
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_meta)

    return train_loader, val_loader


### AMA both keypoints and instance annotations
def train_cocokpinst_factory(args, target_transforms, heads=None, batch_size=None):
    preprocess = train_cocokpinst_preprocess_factory(
        square_edge=args.square_edge,
        augmentation=args.augmentation,
        extended_scale=args.extended_scale,
        orientation_invariant=args.orientation_invariant,
        rescale_images=args.rescale_images,
        args=args,
        heads=heads)

    if args.loader_workers is None:
        args.loader_workers = args.batch_size


    config = 'cif'
    category_ids = [1]
    ball = False

    if 'cifball' in heads:
        config = 'cifball'
        category_ids = [1, 37]
    elif 'cifcentball' in heads:
        config = 'cifcentball'
        category_ids = [1, 37]
    elif 'cifcent' in heads:
        config = 'cifcent'
        category_ids = [1]
        if 'ball' in heads:
            category_ids = [1, 37]
            ball = True
    elif 'ball' in heads:
        config = 'ball'
        category_ids = [37]

    if 'cif' in heads and 'cent' in heads:
        config = 'cif cent'
        if 'ball' in heads:
            category_ids = [1, 37]
            ball = True
    

    train_data = Coco(
        image_dir=args.coco_train_image_dir,
        ann_file=args.cocokp_train_annotations,
        ann_inst_file=args.cocoinst_train_annotations,
        preprocess=preprocess,
        target_transforms=target_transforms,
        n_images=args.n_images,
        category_ids=category_ids,
        image_filter='kp_inst',
        config=config,
        ball=ball,
        filter_for_medium=args.filter_for_medium_coco,
        eval_coco=False,
    )
    
    
    if args.duplicate_data:
        train_data = torch.utils.data.ConcatDataset(
            [train_data for _ in range(args.duplicate_data)])
    train_loader = torch.utils.data.DataLoader(
        train_data, batch_size=batch_size, shuffle=not args.debug,
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_inst_meta,)


    val_data = Coco(
        image_dir=args.coco_val_image_dir,
        ann_file=args.cocokp_val_annotations,
        ann_inst_file=args.cocoinst_val_annotations,
        preprocess=preprocess,
        target_transforms=target_transforms,
        n_images=args.n_images,
        image_filter='kp_inst',
        category_ids=category_ids,
        config=config,
        ball=ball
    )
    if args.duplicate_data:
        val_data = torch.utils.data.ConcatDataset(
            [val_data for _ in range(args.duplicate_data)])
    val_loader = torch.utils.data.DataLoader(
        val_data, batch_size=batch_size, shuffle=False,
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_inst_meta)

    return train_loader, val_loader


def train_keemotion_factory(args, target_transforms, heads=None, batch_size=None):
    preprocess = train_keemotion_preprocess_factory(
        square_edge=args.square_edge,
        augmentation=args.augmentation,
        extended_scale=args.extended_scale,
        orientation_invariant=args.orientation_invariant,
        rescale_images=args.rescale_images,
        args=args,
        heads=heads)

    if args.loader_workers is None:
        args.loader_workers = args.batch_size

    train_data = Keemotion(args.keemotion_dir, 'train', config=args.headnets[0],
        target_transforms=target_transforms, preprocess=preprocess)
    train_loader = torch.utils.data.DataLoader(
        train_data, batch_size=batch_size, shuffle=not args.debug,
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_inst_meta,)
        # timeout=50.)

    val_data = Keemotion(args.keemotion_dir, 'val', config=args.headnets[0],
        target_transforms=target_transforms, preprocess=preprocess)
    val_loader = torch.utils.data.DataLoader(
        val_data, batch_size=batch_size, shuffle=False,
        pin_memory=args.pin_memory, num_workers=args.loader_workers, drop_last=True,
        collate_fn=collate_images_targets_inst_meta,
        timeout=50.)

    return train_loader, val_loader



def train_single_factory(args, target_transforms, dataset=None, heads=None, batch_size=None):
    if dataset in ('deepsport'):
        print('batch size for deepsport', batch_size)
        return train_deepsport_factory(args, target_transforms, heads=heads, batch_size=batch_size)
    if dataset in ('cocokpinst'):
        print('batch size for coco', batch_size)
        return train_cocokpinst_factory(args, target_transforms, heads=heads, batch_size=batch_size)
    if dataset in ('cocokp',):
        return train_cocokp_factory(args, target_transforms)
    if dataset in ('cocodet',):
        return train_cocodet_factory(args, target_transforms)
    if dataset in ('keemotion',):
        print('batch size for keemotion', batch_size)
        return train_keemotion_factory(args, target_transforms, heads=heads, batch_size=batch_size)

    raise Exception('unknown dataset: {}'.format(args.dataset))

def train_factory(args, target_transforms, heads=None):
        
    if '-' in args.dataset:
        if args.dataset_weights is None:
            dataset_weights = [1. for ds in args.dataset.split('-')]
        else:
            dataset_weights = args.dataset_weights
        assert len(dataset_weights) == len(args.dataset.split('-'))
        
        batch_sizes = [int(dw / sum(dataset_weights) * args.batch_size) for dw in dataset_weights]
    else:
        batch_sizes = [args.batch_size]

        return train_single_factory(args, target_transforms, dataset=args.dataset, heads=heads, batch_size=args.batch_size)
    dataloaders = [train_single_factory(args, target_transforms, dataset=ds, heads=heads, batch_size=btch_sz) for ds, btch_sz in zip(args.dataset.split('-'), batch_sizes)]
    train_dataloaders = [tr_dl for tr_dl, _ in dataloaders]
    val_dataloaders = [val_dl for _, val_dl in dataloaders]
    return MultiDataset(heads, train_dataloaders), MultiDataset(heads, val_dataloaders)