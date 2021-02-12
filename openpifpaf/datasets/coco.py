from collections import defaultdict
import copy
import logging
import os

import numpy as np
import torch.utils.data
from PIL import Image

from .. import transforms, utils

import scipy.ndimage

LOG = logging.getLogger(__name__)
STAT_LOG = logging.getLogger(__name__.replace('openpifpaf.', 'openpifpaf.stats.'))


class Coco(torch.utils.data.Dataset):
    """`MS Coco Detection <http://mscoco.org/dataset/#detections-challenge2016>`_ Dataset.

    Args:
        image_dir (string): Root directory where images are downloaded to.
        ann_file (string): Path to json annotation file.
    """

    def __init__(self, image_dir, ann_file, *, ann_inst_file=None, target_transforms=None,
                 n_images=None, preprocess=None,
                 category_ids=None,
                 image_filter='keypoint-annotations',
                 config='cif'):
        if category_ids is None:
            category_ids = [1]

        self.config = config
        print(self.config)

        from pycocotools.coco import COCO  # pylint: disable=import-outside-toplevel
        self.image_dir = image_dir
        self.coco = COCO(ann_file)
        if ann_inst_file is not None:
            self.coco_inst = COCO(ann_inst_file)

        self.category_ids = category_ids
        self.ann_inst_file = ann_inst_file

        if image_filter == 'all':
            self.ids = self.coco.getImgIds()
        elif image_filter == 'annotated':
            self.ids = self.coco.getImgIds(catIds=self.category_ids)
            self.filter_for_annotations()
        elif image_filter == 'keypoint-annotations':
            self.ids_kp = self.coco_kp.getImgIds(catIds=self.category_ids)
            self.filter_for_keypoint_annotations()
        elif image_filter == 'kp_inst':
            # print(self.category_ids)


            if self.category_ids == [1]:
                self.ids = self.coco.getImgIds(catIds=self.category_ids)
                # self.ids_inst = self.coco_inst.getImgIds(catIds=self.category_ids)
                self.filter_for_keypoint_annotations()
            elif self.category_ids == [37]:
                self.ids_ball = self.coco_inst.getImgIds(catIds=self.category_ids)
                self.ids = self.ids_ball
            else:
                self.ids = self.coco.getImgIds(catIds=self.category_ids[0])
                # self.ids_inst = self.coco_inst.getImgIds(catIds=self.category_ids[0])
                self.ids_ball = self.coco_inst.getImgIds(catIds=self.category_ids[1])
                # self.filter_for_keypoint_annotations()
                self.ids += self.ids_ball
                # for i in self.ids_ball:
                #     if i not in self.ids:
                #         self.ids.append(i) 
                
                self.ids = list(dict.fromkeys(self.ids))        ## remove duplicate image Ids
            # print(self.category_ids)
            # print(len(self.ids))
            
            # print(len(self.ids_inst))
            # self.filter_for_annotations()
            ### AMA union of kp and inst annotations
            # self.ids_ = []
            # for idx in self.ids:
            #     if idx in self.ids_inst:
            #         self.ids_.append(idx)
            # self.ids = self.ids_
            

            # if self.category_ids != [1]:
                
            #     self.ids += self.ids_ball
                
            #     self.ids = list(dict.fromkeys(self.ids))        ## remove duplicate image Ids
                
            # self.filter_for_keypoint_annotations_inst()
        else:
            raise Exception('unknown value for image_filter: {}'.format(image_filter))

        if n_images:
            self.ids = self.ids[:n_images]
        LOG.info('Images: %d', len(self.ids))

        

        self.preprocess = preprocess or transforms.EVAL_TRANSFORM
        self.target_transforms = target_transforms

    def filter_for_keypoint_annotations(self):
        LOG.info('filter for keypoint annotations ...')
        def has_keypoint_annotation(image_id):
            ann_ids = self.coco.getAnnIds(imgIds=image_id)
            anns = self.coco.loadAnns(ann_ids)
            for ann in anns:
                if 'keypoints' not in ann:
                    continue
                if any(v > 0.0 for v in ann['keypoints'][2::3]):
                    return True
            return False

        self.ids = [image_id for image_id in self.ids if has_keypoint_annotation(image_id)]
        LOG.info('... done.')

    ###

    def filter_for_keypoint_annotations_inst(self):
        LOG.info('filter for keypoint annotations ...')
        def has_keypoint_annotation_inst(image_id):
            ann_ids = self.coco_inst.getAnnIds(imgIds=image_id, catIds=self.category_ids)
            anns = self.coco_inst.loadAnns(ann_ids)
            for ann in anns:
                if 'keypoints' not in ann:
                    continue
                if any(v > 0.0 for v in ann['keypoints'][2::3]):
                    return True
            return False

        self.ids_inst = [image_id for image_id in self.ids_inst if has_keypoint_annotation_inst(image_id)]
        LOG.info('... done.')

    def filter_for_annotations(self):
        """removes images that only contain crowd annotations"""
        LOG.info('filter for annotations ...')
        def has_annotation(image_id):
            ann_ids = self.coco.getAnnIds(imgIds=image_id, catIds=self.category_ids)
            anns = self.coco.loadAnns(ann_ids)
            for ann in anns:
                if ann.get('iscrowd'):
                    continue
                return True
            return False

        self.ids = [image_id for image_id in self.ids
                    if has_annotation(image_id)]
        LOG.info('... done.')

    def class_aware_sample_weights(self, max_multiple=10.0):
        """Class aware sampling.

        To be used with PyTorch's WeightedRandomSampler.

        Reference: Solution for Large-Scale Hierarchical Object Detection
        Datasets with Incomplete Annotation and Data Imbalance
        Yuan Gao, Xingyuan Bu, Yang Hu, Hui Shen, Ti Bai, Xubin Li and Shilei Wen
        """
        ann_ids = self.coco.getAnnIds(imgIds=self.ids, catIds = self.category_ids)
        anns = self.coco.loadAnns(ann_ids)
        # print(len(anns))

        category_image_counts = defaultdict(int)
        image_categories = defaultdict(set)
        for ann in anns:
            if ann['iscrowd']:
                continue
            image = ann['image_id']
            category = ann['category_id']
            if category in image_categories[image]:
                continue
            image_categories[image].add(category)
            category_image_counts[category] += 1
        # print(category_image_counts)
        weights = [
            sum(
                1.0 / category_image_counts[category_id]
                for category_id in image_categories[image_id]
            )
            for image_id in self.ids
        ]
        # print(weights)
        min_w = min(weights)
        LOG.debug('Class Aware Sampling: minW = %f, maxW = %f', min_w, max(weights))
        max_w = min_w * max_multiple
        weights = [min(w, max_w) for w in weights]
        LOG.debug('Class Aware Sampling: minW = %f, maxW = %f', min_w, max(weights))
        # print(min_w)
        # print(max_w)
        return weights

    def add_center(self, anns, mask, visiblity=2, id_ball=None):
        
        for id_m, msk in enumerate(mask):
            meshgrid = np.indices(msk.shape)
            meshgrid[0] *= msk
            meshgrid[1] *= msk
            center = (meshgrid[0].sum()/msk.sum(),
                    meshgrid[1].sum()/msk.sum())

            keypoints = anns[id_m]['keypoints']
            anns[id_m]['keypoints'].append(int(center[1]))      # add center for y
            anns[id_m]['keypoints'].append(int(center[0]))      # add center for x
            anns[id_m]['keypoints'].append(visiblity)
            # if id_ball is not None:
            #     anns[id_m]['id_ball'] = id_ball

            

        return anns

    def empty_person_keypoint(anns_inst, n_keypoints=17, category_id=37):
        
        anns = []
        keypoints = []
        for _ in range(3*n_keypoints):
            keypoints.append(0)
        
        for i in anns_inst:
            id = i['id']
            image_id = i['image_id']
            anns.append({'num_keypoints': 0,
                'area': 0.,
                'iscrowd': 0,
                'keypoints': keypoints,
                'image_id': image_id,
                'bbox': [0., 0., 0., 0.],
                'category_id': category_id,
                'id': id})
        
        return anns


    def __getitem__(self, index):

        image_id = self.ids[index]

        image_info = self.coco.loadImgs(image_id)[0]
        LOG.debug(image_info)
        with open(os.path.join(self.image_dir, image_info['file_name']), 'rb') as f:
            image = Image.open(f).convert('RGB')

        meta = {
            'dataset_index': index,
            'image_id': image_id,
            'file_name': image_info['file_name'],
        }

        if 'flickr_url' in image_info:
            _, flickr_file_name = image_info['flickr_url'].rsplit('/', maxsplit=1)
            flickr_id, _ = flickr_file_name.split('_', maxsplit=1)
            meta['flickr_full_page'] = 'http://flickr.com/photo.gne?id={}'.format(flickr_id)

        anns = []
        mask = []

        ann_ids = self.coco.getAnnIds(imgIds=image_id)
        anns = self.coco.loadAnns(ann_ids)
        

        # mask = []

        if self.ann_inst_file is not None:
            ann_ids_inst = self.coco_inst.getAnnIds(imgIds=image_id, catIds=[1])
            anns_inst = self.coco_inst.loadAnns(ann_ids_inst)
            
            for i in anns_inst:
                ann_mask_id = i['id']
                # print(i)
                # print(ann_mask_id)
                mask.append(self.coco_inst.annToMask(i) * ann_mask_id)

            # print('annsssssssssssssssssssssssss')
            # print(len(anns))
            # print(anns)
            # print('insssssssssssssssssssssssss')
            # print(anns_inst)
        #     print(len(anns_inst))
        # print(anns.shape)
        if self.config == 'cif':
            pass

        elif self.config == 'cifcent':
            anns = self.add_center(anns, mask)

        elif self.config == 'cifball':
            anns = self.add_center(anns, mask, visiblity=0)        # add fake ball keypoint
            mask_ball = []
            ann_ids_inst = self.coco_inst.getAnnIds(imgIds=image_id, catIds=[37])
            anns_inst = self.coco_inst.loadAnns(ann_ids_inst)
            for i in anns_inst:
                ann_mask_id = i['id']
                mask_ball.append(self.coco_inst.annToMask(i) * ann_mask_id) 

            anns_ball = self.empty_person_keypoint(anns_inst)     # add fake people
            anns_ball = self.add_center(anns_ball, mask_ball)        # add ball keypoint
            anns += anns_ball
            mask += mask_ball

        elif self.config == 'cifcentball':
            anns = self.add_center(anns, mask)
            anns = self.add_center(anns, mask, visiblity=0)        # add fake ball keypoint
            mask_ball = []
            ann_ids_inst = self.coco_inst.getAnnIds(imgIds=image_id, catIds=[37])
            anns_inst = self.coco_inst.loadAnns(ann_ids_inst)
            for i in anns_inst:
                ann_mask_id = i['id']
                mask_ball.append(self.coco_inst.annToMask(i) * ann_mask_id)

            anns_ball = self.empty_person_keypoint(anns_inst, n_keypoints=18)     # add fake people
            anns_ball = self.add_center(anns_ball, mask_ball)        # add ball keypoint
            anns += anns_ball

        else:
            raise NotImplementedError

        
        # print(len(anns))
        # print(len(mask))
        # anns = self.empty_person_keypoint(mask, image_id)

        anns = copy.deepcopy(anns)
        mask = copy.deepcopy(mask)
        # anns_inst = copy.deepcopy(anns_inst)

        # anns.append(np.squeeze(anns_inst)[0])
        # return anns
        

        

        
        # hei = mask[0].shape[0]
        # wid = mask[0].shape[1]
        # mask_copy = mask.copy()


        # ## encode the masks
        # masks = np.zeros((hei, wid))    
        # for i in range(len(mask)):    
        #     masks [mask[i] == 1] = i+1

        # if np.unique(masks).tolist() == [0.0, 1.0]:
        #     torch.save((image,masks,meta),'image_empt_coco.pt')

        # print('coco')

        
        # preprocess image and annotations
        # image, anns, meta = self.preprocess(image, anns, meta)
        
        
        ### AMA
        # print('111')
        # print(image)
        # print(len(anns))
        # print(anns)
        # print(anns[0].shape)
        # print(mask) # a list of masks of people in image
        # print(meta)

        # if self.ann_inst_file is not None:
        #     anns = self.add_center(image,anns, mask)
        
        image, anns, mask, meta = self.preprocess(image, anns, mask, meta)
        # print('222')
        # print(len(anns))
        # print(anns[0].shape)
        # print(image)
        # print(anns)
        # print(meta)
        # mask valid TODO still necessary?
        
        valid_area = meta['valid_area']
        utils.mask_valid_area(image, valid_area)

        LOG.debug(meta)

        # print('______valid area______')
        # print(valid_area)
        # print(image.shape)

        # log stats
        for ann in anns:
            if getattr(ann, 'iscrowd', False):
                continue
            if not np.any(ann['keypoints'][:, 2] > 0.0):
                continue
            STAT_LOG.debug({'bbox': [int(v) for v in ann['bbox']]})

        # transform targets
        if self.target_transforms is not None:
            anns = [t(image, anns, mask, meta) for t in self.target_transforms]

        
        # hei_wid = mask[0].shape[0]
        # masks = np.zeros((49, 49))
        # # print(mask[0].sum())
        # for i in range(len(mask)):
        #     mask[i] = scipy.ndimage.zoom(mask[i], 49/hei_wid, order=1)
        #     masks [mask[i] == 1] = i+1
        ###
        # # anns.append(mask)
        # print("annnsnsnsnsn")
        # # print(anns.shape)
        # print(len(anns))
        # print(len(anns[0]))
        # # print(anns[0].shape)
        # print(len(anns[0][0]))
        # # print(len(anns[0][0][0]))
        # # print(len(anns[0][0][16]))
        # # print(len(anns[0][1]))
        # # print(len(anns[0][1][0]))
        # # print(len(anns[0][1][16]))        
        # # print(len(anns[0][2]))
        # # print(len(anns[0][2][0]))
        # # print(len(anns[0][2][16]))
        # print(len(anns[1]))
        # # print(anns[1].shape)
        # print(len(anns[1][0]))
        # print(anns)
        # print(meta)
        # import os
        
        
        # import pickle
        # if not os.path.isfile('coco.pickle'):
        #     with open('coco.pickle','wb') as f:
        #         pickle.dump((image, anns, meta),f)
        return image, anns, meta

    def __len__(self):
        return len(self.ids)
        
