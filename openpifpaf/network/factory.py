import logging
import os
from time import asctime
import torch

import torchvision
from traitlets.traitlets import default

from . import basenetworks, heads, nets
from .. import datasets

# generate hash values with: shasum -a 256 filename.pkl


CHECKPOINT_URLS = {
    'resnet50': ('http://github.com/vita-epfl/openpifpaf-torchhub/releases/download/'
                 'v0.11.2/resnet50-200527-171310-cif-caf-caf25-o10s-c0b7ae80.pkl'),
    'shufflenetv2k16w': ('http://github.com/vita-epfl/openpifpaf-torchhub/releases/download/'
                         'v0.11.0/shufflenetv2k16w-200510-221334-cif-caf-caf25-o10s-604c5956.pkl'),
    'shufflenetv2k30w': ('http://github.com/vita-epfl/openpifpaf-torchhub/releases/download/'
                         'v0.11.0/shufflenetv2k30w-200510-104256-cif-caf-caf25-o10s-0b5ba06f.pkl'),
}

LOG = logging.getLogger(__name__)


def factory_from_args(args):
    return factory(
        checkpoint=args.checkpoint,
        base_name=args.basenet,
        head_names=args.headnets,
        pretrained=args.pretrained,
        dense_connections=getattr(args, 'dense_connections', False),
        cross_talk=args.cross_talk,
        two_scale=args.two_scale,
        multi_scale=args.multi_scale,
        multi_scale_hflip=args.multi_scale_hflip,
        download_progress=args.download_progress,
        weights=args.weights,
        load_pif_weights=args.enable_load_pif_weights,
        player_only=args.player_only,
        ball_only=args.ball_only,
        segmentation_only=args.segmentation_only,
    )


def local_checkpoint_path(checkpoint):
    if os.path.exists(checkpoint):
        return checkpoint

    if checkpoint in CHECKPOINT_URLS:
        url = CHECKPOINT_URLS[checkpoint]

        base_dir = os.path.join(
            os.getenv('XDG_CACHE_HOME', os.path.join(os.getenv('HOME'), '.cache')),
            'torch',
        )
        if hasattr(torch, 'hub') and hasattr(torch.hub, 'get_dir'):
            # new in pytorch 1.6.0
            base_dir = torch.hub.get_dir()
        file_name = os.path.join(
            base_dir,
            'checkpoints',
            os.path.basename(url),
        )
        print(file_name, url, os.path.basename(url))

        if os.path.exists(file_name):
            return file_name

    return None


# pylint: disable=too-many-branches,too-many-statements
def factory(
        *,
        checkpoint=None,
        base_name=None,
        head_names=None,
        pretrained=True,
        dense_connections=False,
        cross_talk=0.0,
        two_scale=False,
        multi_scale=False,
        multi_scale_hflip=True,
        download_progress=True,
        weights=None,
        load_pif_weights=False,
        add_ball_head_from_checkpoint=None,
        player_only=False,
        ball_only=False,
        segmentation_only=False):

    if base_name:
        assert head_names
        if checkpoint is None:
            # assert checkpoint is None
            net_cpu = factory_from_scratch(base_name, head_names, pretrained=pretrained)
            epoch = 0
            if weights is not None:
                checkpoint = torch.load(weights)
                if 'model_state_dict' in checkpoint:
                    old_model_state_dict = checkpoint['model_state_dict']
                    net_cpu.load_state_dict(old_model_state_dict)

                else:
                    old_model = checkpoint['model']
                    state_dict = old_model.base_net.state_dict()
                    net_cpu.base_net.load_state_dict(state_dict)
                    if load_pif_weights: 
                        pif_state_dict = old_model.head_nets[0].state_dict()
                        net_cpu.head_nets[0].load_state_dict(pif_state_dict)
        else:
            checkpoint = torch.load(checkpoint, map_location='cpu')
            print('NETWORK FACTORY: model loaded from checkpoint')
            if 'model_state_dict' in checkpoint:
                print('NETWORK FACTORY: model has state dict')
                net_cpu = factory_from_scratch(base_name, head_names, pretrained=pretrained)
                if player_only:
                    loaded_state_dict = checkpoint['model_state_dict']
                    base_net_dict = {k.replace('base_net.', ''): v for k,v in loaded_state_dict.items() if k.startswith('base_net')}
                    net_cpu.base_net.load_state_dict(base_net_dict)
                    head_net_dict = {k.replace('head_nets.0.', ''): v for k,v in loaded_state_dict.items() if k.startswith('head_nets.0')}
                    net_cpu.head_nets[0].load_state_dict(head_net_dict)
                    head_net_dict = {k.replace('head_nets.1.', ''): v for k,v in loaded_state_dict.items() if k.startswith('head_nets.1')}
                    net_cpu.head_nets[1].load_state_dict(head_net_dict)
                    head_net_dict = {k.replace('head_nets.3.', ''): v for k,v in loaded_state_dict.items() if k.startswith('head_nets.3')}
                    net_cpu.head_nets[2].load_state_dict(head_net_dict)
                    epoch = checkpoint['epoch']
                
                elif ball_only:
                    loaded_state_dict = checkpoint['model_state_dict']
                    base_net_dict = {k.replace('base_net.', ''): v for k,v in loaded_state_dict.items() if k.startswith('base_net')}
                    net_cpu.base_net.load_state_dict(base_net_dict)
                    head_net_dict = {k.replace('head_nets.2.', ''): v for k,v in loaded_state_dict.items() if k.startswith('head_nets.2')}
                    net_cpu.head_nets[0].load_state_dict(head_net_dict)
                    epoch = checkpoint['epoch']

                elif segmentation_only:
                    loaded_state_dict = checkpoint['model_state_dict']
                    base_net_dict = {k.replace('base_net.', ''): v for k,v in loaded_state_dict.items() if k.startswith('base_net')}
                    net_cpu.base_net.load_state_dict(base_net_dict)
                    head_net_dict = {k.replace('head_nets.1.', ''): v for k,v in loaded_state_dict.items() if k.startswith('head_nets.1')}
                    net_cpu.head_nets[0].load_state_dict(head_net_dict)
                    head_net_dict = {k.replace('head_nets.3.', ''): v for k,v in loaded_state_dict.items() if k.startswith('head_nets.3')}
                    net_cpu.head_nets[1].load_state_dict(head_net_dict)
                    epoch = checkpoint['epoch']
                
                else:
                    net_cpu.load_state_dict(checkpoint['model_state_dict'])
                    print('NETWORK FACTORY: state dict loaded')
                    epoch = checkpoint['epoch']

                    if add_ball_head_from_checkpoint is not None:
                        checkpoint_ball = torch.load(add_ball_head_from_checkpoint, map_location='cpu')
                        net_cpu.head_nets[2].load_state_dict(checkpoint_ball['model_state_dict'].head_nets[0])
                
                # normalize for backwards compatibility
                nets.model_migration(net_cpu)

                # initialize for eval
                net_cpu.eval()

            else:
                raise 'model_state_dict not in checkpoint dict! if the checkpoint is .pkl remove --basenet and --headnets!'
    else:
        assert base_name is None
        assert head_names is None

        if not checkpoint:
            checkpoint = 'shufflenetv2k16w'

        if checkpoint == 'resnet18':
            raise Exception('this pretrained model is currently not available')
        if checkpoint == 'resnet101':
            raise Exception('this pretrained model is currently not available')
        checkpoint = CHECKPOINT_URLS.get(checkpoint, checkpoint)

        if checkpoint.startswith('http'):
            checkpoint = torch.hub.load_state_dict_from_url(
                checkpoint,
                check_hash=not checkpoint.startswith('https'),
                progress=download_progress)
        else:
            checkpoint = torch.load(checkpoint)

        net_cpu = checkpoint['model']
        epoch = checkpoint['epoch']

        # normalize for backwards compatibility
        nets.model_migration(net_cpu)

        # initialize for eval
        net_cpu.eval()

    cif_indices = [0]
    caf_indices = [1]
    if not any(isinstance(h.meta, heads.AssociationMeta) for h in net_cpu.head_nets):
        caf_indices = []
    if dense_connections and not multi_scale:
        caf_indices = [1, 2]
    elif dense_connections and multi_scale:
        cif_indices = [v * 3 + 1 for v in range(10)]
        caf_indices = [v * 3 + 2 for v in range(10)]

    if isinstance(net_cpu.head_nets[0].meta, heads.DetectionMeta):
        net_cpu.process_heads = heads.CifdetCollector(cif_indices)

    elif net_cpu.head_nets[0].meta.name == 'pan' and net_cpu.head_nets[1].meta.name == 'cent':
        net_cpu.process_heads = heads.PanCentCollector(cif_indices)

    elif len(net_cpu.head_nets) == 2 and isinstance(net_cpu.head_nets[1].meta, heads.PanopticDeeplabMeta):
        net_cpu.process_heads = heads.CifPanCollector(cif_indices)
    
    elif len(net_cpu.head_nets) == 3 and isinstance(net_cpu.head_nets[1].meta, heads.PanopticDeeplabMeta) and net_cpu.head_nets[2].meta.name=='cent':
        net_cpu.process_heads = heads.CifPanCentCollector(cif_indices)
    elif len(net_cpu.head_nets) == 3 and isinstance(net_cpu.head_nets[1].meta, heads.PanopticDeeplabMeta):
        net_cpu.process_heads = heads.CifPanBallCollector(cif_indices)

    elif len(net_cpu.head_nets) == 4 and isinstance(net_cpu.head_nets[1].meta, heads.PanopticDeeplabMeta):
        net_cpu.process_heads = heads.CifPanBallCentCollector(cif_indices)

    else:
        net_cpu.process_heads = heads.CifCafCollector(cif_indices, caf_indices)
    net_cpu.cross_talk = cross_talk

    if two_scale:
        net_cpu = nets.Shell2Scale(net_cpu.base_net, net_cpu.head_nets)

    if multi_scale:
        net_cpu = nets.ShellMultiScale(net_cpu.base_net, net_cpu.head_nets,
                                       process_heads=net_cpu.process_heads,
                                       include_hflip=multi_scale_hflip)

    return net_cpu, epoch


# pylint: disable=too-many-return-statements
def factory_from_scratch(basename, head_names, *, pretrained=True):
    head_metas = datasets.headmeta.factory(head_names, basename=basename)

    if 'resnet18' in basename:
        base_vision = torchvision.models.resnet18(pretrained)
        return resnet_factory_from_scratch(basename, base_vision, 512, head_metas)
    if 'resnet50' in basename:
        base_vision = torchvision.models.resnet50(pretrained)
        return resnet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if 'resnet101' in basename:
        base_vision = torchvision.models.resnet101(pretrained)
        return resnet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if 'resnet152' in basename:
        base_vision = torchvision.models.resnet152(pretrained)
        return resnet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if 'resnet260' in basename:
        assert pretrained is False
        base_vision = torchvision.models.ResNet(
            torchvision.models.resnet.Bottleneck, [3, 8, 72, 3])
        return resnet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if 'resnext50' in basename:
        base_vision = torchvision.models.resnext50_32x4d(pretrained)
        return resnet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if 'resnext101' in basename:
        base_vision = torchvision.models.resnext101_32x8d(pretrained)
        return resnet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename == 'shufflenetv2x1':
        base_vision = torchvision.models.shufflenet_v2_x1_0(pretrained)
        return shufflenet_factory_from_scratch(basename, base_vision, 1024, head_metas)
    if basename.startswith('shufflenetv2x2'):
        base_vision = torchvision.models.shufflenet_v2_x2_0(pretrained)
        return shufflenet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k16w'):
        base_vision = basenetworks.ShuffleNetV2K(
            [4, 8, 4], [24, 348, 696, 1392, 1392],
        )
        return generic_factory_from_scratch(basename, base_vision, 1392, head_metas)
    if basename.startswith('shufflenetv2k16'):
        base_vision = torchvision.models.ShuffleNetV2(
            [4, 8, 4], [24, 348, 696, 1392, 1392],
        )
        return shufflenet_factory_from_scratch(basename, base_vision, 1392, head_metas)
    if basename.startswith('shufflenetv2k20w'):
        base_vision = basenetworks.ShuffleNetV2K(
            [5, 10, 5], [32, 512, 1024, 2048, 2048],
        )
        return generic_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k20'):
        base_vision = torchvision.models.ShuffleNetV2(
            [5, 10, 5], [32, 512, 1024, 2048, 2048],
        )
        return shufflenet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k30w'):
        base_vision = basenetworks.ShuffleNetV2K(
            [8, 16, 6], [32, 512, 1024, 2048, 2048],
        )
        return generic_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k30'):
        base_vision = torchvision.models.ShuffleNetV2(
            [8, 16, 6], [32, 512, 1024, 2048, 2048],
        )
        return shufflenet_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k44wgn'):
        base_vision = basenetworks.ShuffleNetV2K(
            [12, 24, 8], [32, 512, 1024, 2048, 2048],
            layer_norm=lambda x: torch.nn.GroupNorm(32 if x > 100 else 4, x, eps=1e-4),
        )
        return generic_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k44win'):
        base_vision = basenetworks.ShuffleNetV2K(
            [12, 24, 8], [32, 512, 1024, 2048, 2048],
            layer_norm=lambda x: torch.nn.InstanceNorm2d(
                x, eps=1e-4, momentum=0.01, affine=True, track_running_stats=True),
        )
        return generic_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k44w'):
        base_vision = basenetworks.ShuffleNetV2K(
            [12, 24, 8], [32, 512, 1024, 2048, 2048],
        )
        return generic_factory_from_scratch(basename, base_vision, 2048, head_metas)
    if basename.startswith('shufflenetv2k44'):
        base_vision = torchvision.models.ShuffleNetV2(
            [12, 24, 8], [32, 512, 1024, 2048, 2048],
        )
        return shufflenet_factory_from_scratch(basename, base_vision, 2048, head_metas)

    raise Exception('unknown base network in {}'.format(basename))


def generic_factory_from_scratch(basename, base_vision, out_features, head_metas):
    basenet = basenetworks.BaseNetwork(
        base_vision,
        basename,
        stride=16,
        out_features=out_features,
    )

    headnets = [heads.CompositeFieldFused(h, basenet.out_features) for h in head_metas]

    net_cpu = nets.Shell(basenet, headnets)
    nets.model_defaults(net_cpu)
    LOG.debug(net_cpu)
    return net_cpu


def shufflenet_factory_from_scratch(basename, base_vision, out_features, head_metas):
    blocks = [
        base_vision.conv1,
        # base_vision.maxpool,
        base_vision.stage2,
        base_vision.stage3,
        base_vision.stage4,
        base_vision.conv5,
    ]

    panoptic = len([hm for hm in head_metas if hm.name == "pan"]) > 0
    

    BaseNetwork = basenetworks.BaseNetworkWithSkips if panoptic else basenetworks.BaseNetwork
    basenet = BaseNetwork(
        torch.nn.Sequential(*blocks),
        basename,
        stride=16,
        out_features=out_features,
    )

    headnets = [facrtory_head_single(hd, basenet.out_features) for hd in head_metas]


    net_cpu = nets.Shell(basenet, headnets)
    nets.model_defaults(net_cpu)
    LOG.debug(net_cpu)
    return net_cpu


def resnet_factory_from_scratch(basename, base_vision, out_features, head_metas):
    resnet_factory = basenetworks.ResnetBlocks(base_vision)

    # input block
    use_pool = 'pool0' in basename
    conv_stride = 2
    if 'is4' in basename:
        conv_stride = 4
    if 'is1' in basename:
        conv_stride = 1
    output_stride = conv_stride

    pool_stride = 2
    if 'pool0s4' in basename:
        pool_stride = 4
    output_stride *= pool_stride if use_pool else 1

    # all blocks
    blocks = [
        resnet_factory.input_block(use_pool, conv_stride, pool_stride),
        resnet_factory.block2(),  # no stride
        resnet_factory.block3(),
        resnet_factory.block4(),
    ]
    output_stride *= 4
    if 'block4' not in basename:
        blocks.append(resnet_factory.block5())
        output_stride *= 2
    else:
        out_features //= 2

    panoptic = len([hm for hm in head_metas if hm.name == "pan"]) > 0
    # has_ball = len([hm for hm in head_metas if hm.name == "ball"]) > 0

    BaseNetwork = basenetworks.BaseNetworkWithSkips if panoptic else basenetworks.BaseNetwork
    basenet = BaseNetwork(
        torch.nn.Sequential(*blocks),
        basename,
        stride=output_stride,
        out_features=out_features,
    )

    headnets = [facrtory_head_single(hd, basenet.out_features) for hd in head_metas]



    net_cpu = nets.Shell(basenet, headnets)
    nets.model_defaults(net_cpu)
    return net_cpu

def facrtory_head_single(head_meta, out_features):
    if head_meta.name == 'pan':
        return heads.PanopticDeeplabHead(head_meta, out_features)
    # elif head_meta.name == 'ball':
    #     heads.CompositeFieldFused(head_meta, out_features)
    elif head_meta.name in ['cif', 'cifcent', 'ball', 'cent']:
        return heads.CompositeFieldFused(head_meta, out_features)

def configure(args):
    # configure CompositeField
    heads.CompositeField.dropout_p = args.head_dropout
    heads.CompositeField.quad = args.head_quad
    heads.CompositeFieldFused.dropout_p = args.head_dropout
    heads.CompositeFieldFused.quad = args.head_quad


def cli(parser):
    group = parser.add_argument_group('network configuration')
    group.add_argument('--checkpoint', default=None,
                       help=('Load a model from a checkpoint. '
                             'Use "resnet50", "shufflenetv2k16w" '
                             'or "shufflenetv2k30w" for pretrained OpenPifPaf models.'))
    group.add_argument('--basenet', default=None,
                       help='base network, e.g. resnet50')
    group.add_argument('--headnets', default=None, nargs='+',
                       help='head networks')
    group.add_argument('--no-pretrain', dest='pretrained', default=True, action='store_false',
                       help='create model without ImageNet pretraining')
    group.add_argument('--two-scale', default=False, action='store_true',
                       help='[experimental]')
    group.add_argument('--multi-scale', default=False, action='store_true',
                       help='[experimental]')
    group.add_argument('--no-multi-scale-hflip',
                       dest='multi_scale_hflip', default=True, action='store_false',
                       help='[experimental]')
    group.add_argument('--cross-talk', default=0.0, type=float,
                       help='[experimental]')
    group.add_argument('--no-download-progress', dest='download_progress',
                       default=True, action='store_false',
                       help='suppress model download progress bar')
    group.add_argument('--weights',
                       default=None,
                       help='load network weights')
    
    group.add_argument('--add-ball-head-from-checkpoint',
                       default=None,
                       help='load weights of the ball')

    group = parser.add_argument_group('head')
    group.add_argument('--head-dropout', default=heads.CompositeFieldFused.dropout_p, type=float,
                       help='[experimental] zeroing probability of feature in head input')
    group.add_argument('--head-quad', default=heads.CompositeFieldFused.quad, type=int,
                       help='number of times to apply quad (subpixel conv) to heads')


    group.add_argument('--enable-freeze-encoder', default=False, action='store_true')

    group.add_argument('--enable-load-pif-weights', default=False, action='store_true')

    group.add_argument('--player-only', default=False, action='store_true')
    group.add_argument('--ball-only', default=False, action='store_true')
    group.add_argument('--segmentation-only', default=False, action='store_true')