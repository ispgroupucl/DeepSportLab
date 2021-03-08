import copy
import logging

import numpy as np
import PIL

from .preprocess import Preprocess

LOG = logging.getLogger(__name__)


class _HorizontalSwap():
    def __init__(self, keypoints, hflip):
        self.keypoints = keypoints
        self.hflip = hflip

    def __call__(self, keypoints):
        target = np.zeros(keypoints.shape)
        # print('cons',len(keypoints))
        # print('hflip',len(self.keypoints))
        for source_i, xyv in enumerate(keypoints):
            # print('source i', source_i)
            source_name = self.keypoints[source_i]
            target_name = self.hflip.get(source_name)
            if target_name:
                target_i = self.keypoints.index(target_name)
            else:
                target_i = source_i
            
            target[target_i] = xyv

        return target


class HFlip(Preprocess):
    def __init__(self, keypoints, hflip):
        self.swap = _HorizontalSwap(keypoints, hflip)

    ### AMA
    def __call__(self, image, anns, meta):
        meta = copy.deepcopy(meta)
        anns = copy.deepcopy(anns)
        # mask = copy.deepcopy(mask)

        w, _ = image.size
        image = image.transpose(PIL.Image.FLIP_LEFT_RIGHT)
        for ann in anns:
            # print('before', ann['kp_ball'])
            ann['keypoints'][:, 0] = -ann['keypoints'][:, 0] - 1.0 + w
            if self.swap is not None and not ann['iscrowd']:
                ann['keypoints'] = self.swap(ann['keypoints'])
                meta['horizontal_swap'] = self.swap
            ann['bbox'][0] = -(ann['bbox'][0] + ann['bbox'][2]) - 1.0 + w

            if 'kp_ball' in ann:
                ann['kp_ball'][:, 0] = -ann['kp_ball'][:, 0] - 1.0 + w

            ann['bmask'] = np.flip(ann['bmask'], axis=1)
            # print('after', ann['kp_ball'])

        ### AMA
        # for mask_idx in range(len(mask)):
        #     mask[mask_idx] = np.flip(mask[mask_idx], axis=1)

        assert meta['hflip'] is False
        meta['hflip'] = True

        # print('valid area (hflip)', meta['valid_area'])
        meta['valid_area'][0] = -(meta['valid_area'][0] + meta['valid_area'][2]) + w
        # print('valid area (hflip) a', meta['valid_area'])

        return image, anns, meta
