from ..network.heads import AssociationMeta, DetectionMeta, IntensityMeta, SegmentationMeta, PanopticDeeplabMeta
from .constants import (
    COCO_CATEGORIES,
    COCO_KEYPOINTS,
    COCO_PERSON_SKELETON,
    COCO_PERSON_SIGMAS,
    COCO_UPRIGHT_POSE,
    DENSER_COCO_PERSON_CONNECTIONS,
    KINEMATIC_TREE_SKELETON,
)
import numpy as np

def factory(head_names):
    if head_names is None:
        return None

    num_sem_classes = 2
    if 'cifball' in head_names or 'cifcentball' in head_names:      # handle num classes in panoptic head
        num_sem_classes = 3

    return [factory_single(hn, num_sem_classes=num_sem_classes) for hn in head_names]


def factory_single(head_name, num_sem_classes=None):
    if 'cifdet' in head_name:
        return DetectionMeta(head_name, COCO_CATEGORIES)

    ### 4 options for cif head
    ''' 1) normal cif
        2) cif + center
        3) cif + ball
        4) cif + center + ball
    '''
    ## 4
    if 'cifcentball' in head_name:
        return IntensityMeta(head_name,
                             COCO_KEYPOINTS,
                             COCO_PERSON_SIGMAS,
                             COCO_UPRIGHT_POSE,
                             COCO_PERSON_SKELETON)
    ## 2
    if 'cifcent' in head_name:
        return IntensityMeta(head_name,
                             COCO_KEYPOINTS[:-1],
                             COCO_PERSON_SIGMAS[:-1],
                             COCO_UPRIGHT_POSE,
                             COCO_PERSON_SKELETON)
    ## 3
    if 'cifball' in head_name:
        return IntensityMeta(head_name,
                             np.concatenate((COCO_KEYPOINTS[:-2],np.expand_dims(COCO_KEYPOINTS[-1],axis=0))),
                             np.concatenate((COCO_PERSON_SIGMAS[:-2],np.expand_dims(COCO_PERSON_SIGMAS[-1],axis=0))),
                             COCO_UPRIGHT_POSE[:-1],
                             COCO_PERSON_SKELETON)
    ## 1
    if 'pif' in head_name or 'cif' in head_name:
        return IntensityMeta(head_name,
                             COCO_KEYPOINTS[:-2],
                             COCO_PERSON_SIGMAS[:-2],
                             COCO_UPRIGHT_POSE[:-1],
                             COCO_PERSON_SKELETON)

    # if 'ball' in head_name:
    #     return IntensityMeta(head_name,
    #                         COCO_KEYPOINTS[-2:],
    #                         COCO_PERSON_SIGMAS[-2:],
    #                         COCO_UPRIGHT_POSE[:-1],
    #                         COCO_PERSON_SKELETON)
    if 'caf25' in head_name:
        return AssociationMeta(head_name,
                               COCO_KEYPOINTS,
                               COCO_PERSON_SIGMAS,
                               COCO_UPRIGHT_POSE,
                               DENSER_COCO_PERSON_CONNECTIONS,
                               sparse_skeleton=COCO_PERSON_SKELETON,
                               only_in_field_of_view=True)
    if 'caf16' in head_name:
        return AssociationMeta(head_name,
                               COCO_KEYPOINTS,
                               COCO_PERSON_SIGMAS,
                               COCO_UPRIGHT_POSE,
                               KINEMATIC_TREE_SKELETON)
    if head_name == 'caf':
        return AssociationMeta(head_name,
                               COCO_KEYPOINTS,
                               COCO_PERSON_SIGMAS,
                               COCO_UPRIGHT_POSE,
                               COCO_PERSON_SKELETON)

    ### AMA add meta name
    if 'seg' in head_name:
        return SegmentationMeta(head_name,
                                COCO_KEYPOINTS,
                                ['people'],
                                COCO_PERSON_SKELETON)

    if 'pan' in head_name:
        return PanopticDeeplabMeta(head_name,
                                   COCO_KEYPOINTS,
                                   COCO_PERSON_SKELETON,
                                   num_classes=(num_sem_classes, 2))


    raise NotImplementedError
