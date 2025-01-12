from collections import defaultdict
import logging
from queue import PriorityQueue
import time

import numpy as np

from .generator import Generator
from ...annotation import Annotation
from ..field_config import FieldConfig
from ..cif_hr import CifHr
from ..cif_seeds import CifSeeds
from ..caf_scored import CafScored
from .. import nms as nms_module
from ..occupancy import Occupancy
from ... import visualizer

# pylint: disable=import-error
from ...functional import caf_center_s

LOG = logging.getLogger(__name__)

### AMA
class CifSeg(Generator):
    """Generate CifCaf poses from fields.

    :param: nms: set to None to switch off non-maximum suppression.
    """
    connection_method = 'blend'
    occupancy_visualizer = visualizer.Occupancy()
    force_complete = False
    greedy = False
    keypoint_threshold = 0.0

    def __init__(self, field_config: FieldConfig, *,
                 keypoints,
                 skeleton,
                 out_skeleton=None,
                 confidence_scales=None,
                 worker_pool=None,
                 nms=True):
        super().__init__(worker_pool)
        if nms is True:
            nms = nms_module.Keypoints()

        self.field_config = field_config

        self.keypoints = keypoints
        self.skeleton = skeleton
        self.skeleton_m1 = np.asarray(skeleton) - 1
        self.out_skeleton = out_skeleton or skeleton
        self.confidence_scales = confidence_scales
        self.nms = nms

        self.timers = defaultdict(float)

        # init by_target and by_source
        self.by_target = defaultdict(dict)
        for caf_i, (j1, j2) in enumerate(self.skeleton_m1):
            self.by_target[j2][j1] = (caf_i, True)
            self.by_target[j1][j2] = (caf_i, False)
        self.by_source = defaultdict(dict)
        for caf_i, (j1, j2) in enumerate(self.skeleton_m1):
            self.by_source[j1][j2] = (caf_i, True)
            self.by_source[j2][j1] = (caf_i, False)

    def __call__(self, fields, initial_annotations=None):
        start = time.perf_counter()
        if not initial_annotations:
            initial_annotations = []
        LOG.debug('initial annotations = %d', len(initial_annotations))


        ### AMA
        # decoder of Maxime's
        self.fields = fields
        predictions = self.cluster() # masks from maxime's head





    
        


        # if self.field_config.cif_visualizers:
        #     for vis, cif_i in zip(self.field_config.cif_visualizers, self.field_config.cif_indices):
        #         vis.predicted(fields[cif_i])
        # if self.field_config.caf_visualizers:
        #     for vis, caf_i in zip(self.field_config.caf_visualizers, self.field_config.caf_indices):
        #         vis.predicted(fields[caf_i])

        # cifhr = CifHr(self.field_config).fill(fields)
        # seeds = CifSeeds(cifhr.accumulated, self.field_config).fill(fields)
        # caf_scored = CafScored(cifhr.accumulated, self.field_config, self.skeleton).fill(fields)

        # occupied = Occupancy(cifhr.accumulated.shape, 2, min_scale=4)
        # annotations = []

        # def mark_occupied(ann):
        #     for joint_i, xyv in enumerate(ann.data):
        #         if xyv[2] == 0.0:
        #             continue

        #         width = ann.joint_scales[joint_i]
        #         occupied.set(joint_i, xyv[0], xyv[1], width)  # width = 2 * sigma

        # for ann in initial_annotations:
        #     self._grow(ann, caf_scored)
        #     annotations.append(ann)
        #     mark_occupied(ann)

        # for v, f, x, y, s in seeds.get():
        #     if occupied.get(f, x, y):
        #         continue

        #     ann = Annotation(self.keypoints, self.out_skeleton).add(f, (x, y, v))
        #     ann.joint_scales[f] = s
        #     self._grow(ann, caf_scored)
        #     annotations.append(ann)
        #     mark_occupied(ann)

        # self.occupancy_visualizer.predicted(occupied)

        # LOG.debug('annotations %d, %.3fs', len(annotations), time.perf_counter() - start)

        # if self.force_complete:
        #     annotations = self.complete_annotations(cifhr, fields, annotations)

        # if self.nms is not None:
        #     annotations = self.nms.annotations(annotations)

        # LOG.info('%d annotations: %s', len(annotations),
        #          [np.sum(ann.data[:, 2] > 0.1) for ann in annotations])
        # return annotations

    def _grow_connection(self, xy, xy_scale, caf_field):
        assert len(xy) == 2
        assert caf_field.shape[0] == 9

        # source value
        caf_field = caf_center_s(caf_field, xy[0], xy[1], sigma=2.0 * xy_scale)
        if caf_field.shape[1] == 0:
            return 0, 0, 0, 0

        # source distance
        d = np.linalg.norm(((xy[0],), (xy[1],)) - caf_field[1:3], axis=0)

        # combined value and source distance
        v = caf_field[0]
        sigma = 0.5 * xy_scale
        scores = np.exp(-0.5 * d**2 / sigma**2) * v

        if self.connection_method == 'max':
            return self._target_with_maxscore(caf_field[5:], scores)
        if self.connection_method == 'blend':
            return self._target_with_blend(caf_field[5:], scores)
        raise Exception('connection method not known')

    @staticmethod
    def _target_with_maxscore(target_coordinates, scores):
        assert target_coordinates.shape[1] == scores.shape[0]

        max_i = np.argmax(scores)
        max_entry = target_coordinates[:, max_i]

        score = scores[max_i]
        return max_entry[0], max_entry[1], max_entry[3], score

    @staticmethod
    def _target_with_blend(target_coordinates, scores):
        """Blending the top two candidates with a weighted average.

        Similar to the post processing step in
        "BlazeFace: Sub-millisecond Neural Face Detection on Mobile GPUs".
        """
        assert target_coordinates.shape[1] == len(scores)
        if len(scores) == 1:
            return (
                target_coordinates[0, 0],
                target_coordinates[1, 0],
                target_coordinates[3, 0],
                scores[0] * 0.5,
            )

        sorted_i = np.argsort(scores)
        max_entry_1 = target_coordinates[:, sorted_i[-1]]
        max_entry_2 = target_coordinates[:, sorted_i[-2]]

        score_1 = scores[sorted_i[-1]]
        score_2 = scores[sorted_i[-2]]
        if score_2 < 0.01 or score_2 < 0.5 * score_1:
            return max_entry_1[0], max_entry_1[1], max_entry_1[3], score_1 * 0.5

        # TODO: verify the following three lines have negligible speed impact
        d = np.linalg.norm(max_entry_1[:2] - max_entry_2[:2])
        if d > max_entry_1[3] / 2.0:
            return max_entry_1[0], max_entry_1[1], max_entry_1[3], score_1 * 0.5

        return (
            (score_1 * max_entry_1[0] + score_2 * max_entry_2[0]) / (score_1 + score_2),
            (score_1 * max_entry_1[1] + score_2 * max_entry_2[1]) / (score_1 + score_2),
            (score_1 * max_entry_1[3] + score_2 * max_entry_2[3]) / (score_1 + score_2),
            0.5 * (score_1 + score_2),
        )

    def connection_value(self, ann, caf_scored, start_i, end_i, *, reverse_match=True):
        caf_i, forward = self.by_source[start_i][end_i]
        caf_f, caf_b = caf_scored.directed(caf_i, forward)
        xyv = ann.data[start_i]
        xy_scale_s = max(0.0, ann.joint_scales[start_i])

        new_xysv = self._grow_connection(xyv[:2], xy_scale_s, caf_f)
        keypoint_score = np.sqrt(new_xysv[3] * xyv[2])  # geometric mean
        if keypoint_score < self.keypoint_threshold:
            return 0.0, 0.0, 0.0, 0.0
        if new_xysv[3] == 0.0:
            return 0.0, 0.0, 0.0, 0.0
        xy_scale_t = max(0.0, new_xysv[2])

        # reverse match
        if reverse_match:
            reverse_xyv = self._grow_connection(
                new_xysv[:2], xy_scale_t, caf_b)
            if reverse_xyv[2] == 0.0:
                return 0.0, 0.0, 0.0, 0.0
            if abs(xyv[0] - reverse_xyv[0]) + abs(xyv[1] - reverse_xyv[1]) > xy_scale_s:
                return 0.0, 0.0, 0.0, 0.0

        return (new_xysv[0], new_xysv[1], new_xysv[2], keypoint_score)

    @staticmethod
    def p2p_value(source_xyv, caf_scored, source_s, target_xysv, caf_i, forward):
        caf_f, _ = caf_scored.directed(caf_i, forward)
        xy_scale_s = max(0.0, source_s)

        # source value
        caf_field = caf_center_s(caf_f, source_xyv[0], source_xyv[1],
                                 sigma=2.0 * xy_scale_s)
        if caf_field.shape[1] == 0:
            return 0.0

        # distances
        d_source = np.linalg.norm(
            ((source_xyv[0],), (source_xyv[1],)) - caf_field[1:3], axis=0)
        d_target = np.linalg.norm(
            ((target_xysv[0],), (target_xysv[1],)) - caf_field[5:7], axis=0)

        # combined value and source distance
        xy_scale_t = max(0.0, target_xysv[2])
        sigma_s = 0.5 * xy_scale_s
        sigma_t = 0.5 * xy_scale_t
        scores = (
            np.exp(-0.5 * d_source**2 / sigma_s**2) *
            np.exp(-0.5 * d_target**2 / sigma_t**2) *
            caf_field[0]
        )
        return np.sqrt(source_xyv[2] * max(scores))

    def _grow(self, ann, caf_scored, *, reverse_match=True):
        frontier = PriorityQueue()
        in_frontier = set()

        def add_to_frontier(start_i):
            for end_i, (caf_i, _) in self.by_source[start_i].items():
                if ann.data[end_i, 2] > 0.0:
                    continue
                if (start_i, end_i) in in_frontier:
                    continue

                max_possible_score = np.sqrt(ann.data[start_i, 2])
                if self.confidence_scales is not None:
                    max_possible_score *= self.confidence_scales[caf_i]
                frontier.put((-max_possible_score, None, start_i, end_i))
                in_frontier.add((start_i, end_i))
                ann.frontier_order.append((start_i, end_i))

        def frontier_get():
            while frontier.qsize():
                entry = frontier.get()
                if entry[1] is not None:
                    return entry

                _, __, start_i, end_i = entry
                if ann.data[end_i, 2] > 0.0:
                    continue

                new_xysv = self.connection_value(
                    ann, caf_scored, start_i, end_i, reverse_match=reverse_match)
                if new_xysv[3] == 0.0:
                    continue
                score = new_xysv[3]
                if self.greedy:
                    return (-score, new_xysv, start_i, end_i)
                if self.confidence_scales is not None:
                    caf_i, _ = self.by_source[start_i][end_i]
                    score *= self.confidence_scales[caf_i]
                frontier.put((-score, new_xysv, start_i, end_i))

        # seeding the frontier
        for joint_i, v in enumerate(ann.data[:, 2]):
            if v == 0.0:
                continue
            add_to_frontier(joint_i)

        while True:
            entry = frontier_get()
            if entry is None:
                break

            _, new_xysv, jsi, jti = entry
            if ann.data[jti, 2] > 0.0:
                continue

            ann.data[jti, :2] = new_xysv[:2]
            ann.data[jti, 2] = new_xysv[3]
            ann.joint_scales[jti] = new_xysv[2]
            ann.decoding_order.append(
                (jsi, jti, np.copy(ann.data[jsi]), np.copy(ann.data[jti])))
            add_to_frontier(jti)

    def _flood_fill(self, ann):
        frontier = PriorityQueue()

        def add_to_frontier(start_i):
            for end_i in self.by_source[start_i].keys():
                if ann.data[end_i, 2] > 0.0:
                    continue
                start_xyv = ann.data[start_i].tolist()
                frontier.put((-xyv[2], end_i, start_xyv, ann.joint_scales[start_i]))

        for start_i, xyv in enumerate(ann.data):
            if xyv[2] == 0.0:
                continue
            add_to_frontier(start_i)

        while frontier.qsize():
            _, end_i, xyv, s = frontier.get()
            if ann.data[end_i, 2] > 0.0:
                continue
            ann.data[end_i, :2] = xyv[:2]
            ann.data[end_i, 2] = 0.00001
            ann.joint_scales[end_i] = s
            add_to_frontier(end_i)

    def complete_annotations(self, cifhr, fields, annotations):
        start = time.perf_counter()

        caf_scored = CafScored(cifhr.accumulated, self.field_config, self.skeleton,
                               score_th=0.0001).fill(fields)

        for ann in annotations:
            unfilled_mask = ann.data[:, 2] == 0.0
            self._grow(ann, caf_scored, reverse_match=False)
            now_filled_mask = ann.data[:, 2] > 0.0
            updated = np.logical_and(unfilled_mask, now_filled_mask)
            ann.data[updated, 2] = np.minimum(0.001, ann.data[updated, 2])

            # some joints might still be unfilled
            if np.any(ann.data[:, 2] == 0.0):
                self._flood_fill(ann)

        LOG.debug('complete annotations %.3fs', time.perf_counter() - start)
        return annotations








    ### AMA
    def y_foreground(self):
        """predicted foreground probability for each pixel of an image"""
        return self.seed()

    def cluster(self):
        """detect instances within a batch/image"""
        embeddings = self.embedding()
        seeds = self.seed()
        ppsigma = self.ppsigma()

        fg_score = self.y_foreground()
        foreground = fg_score > 0.5
        instances = -foreground.to(torch.int16)
        confidences = []
        # classes = []
        n = 0

        H, W = self.height_width()
        while True:
            remaining_seed = seeds*foreground
            location = torch.argmax(remaining_seed)
            location = self._unravel_index(location, seeds.shape)
            sc, sy, sx = location
            confidence = remaining_seed[sc,sy,sx].item()

            if confidence < 0.5:
                break

            embedding = embeddings[:,sy,sx]
            psigma = self._psigma(ppsigma[:,sy,sx])

            mask = self.gaussian(centroid=embedding,psigma=psigma) > 0.9
            mask = mask & foreground

            # Refine embedding and sigma estimate
            embedding = self.inst_embedding(mask=mask)
            psigma = self._psigma(self.inst_ppsigma(mask=mask))

            mask = self.gaussian(centroid=embedding, psigma=psigma) > 0.5
            mask = mask & foreground

            confidence = self._masked(fg_score, mask).median().item()
            # if confidence < 0.60:  # TODO real empirical estimation
            #     foreground[mask] = False
            #     continue

            # clss = self.y_inst_class(b, mask=mask)

            # register instance
            n += 1
            instances[mask] = n
            confidences.append(confidence)
            # classes.append(clss)
            # remove instance from blank foreground
            foreground[mask] = False
        # set blank foreground to background
        instances[instances==-1] = 0
        return (instances, confidences)

    def _meshgrid(self):
        y = torch.arange(0,1024.)/1024
        x = torch.arange(0,2048.)/1024
        meshgrid = torch.stack([
            y[:,None].expand(-1,2048),
            x[None,:].expand(1024,-1)
        ], dim=0).cuda()

        return meshgrid

    @staticmethod
    def _masked(tensor, mask):
        return tensor[mask.expand_as(tensor)].view(tensor.shape[0], -1)

    def embedding(self, b=None, *, mask=None, **kwargs):
        """predicted embedding on every pixel of batch/image/instance"""
    
        if mask is not None:
            return self._masked(self.embedding(b, **kwargs), mask)
        elif b is not None:
            return self.embedding(**kwargs)[b]
        else:
            embeddings = [self.spatial_embedding(), self.associative_embedding()]
            channels = [embd.shape[1] if embd is not None else 0
                        for embd in embeddings]
            embeddings = [embd for embd in embeddings if embd is not None]

            tensor = torch.cat(embeddings, dim=1)
            tensor._embd_channels = channels
            return tensor

    def spatial_offset(self):
        # spatial = getattr(self.fetches.y, "spatial", None)
        spatial = self.fields[1][1:3]   # get the vector in the fields
        if spatial is not None:
            spatial = spatial.tanh()
        return spatial

    def spatial_embedding(self):
        spatial = self.spatial_offset()
        if spatial is not None:
            N, _, _, C, H, W = spatial.shape
            meshgrid = self._meshgrid()[:,:H,:W]
            spatial = spatial.view(N,C//2,2,H,W) + meshgrid[None,None,:,:,:]
            spatial = spatial.view(N,C,H,W)
        return spatial

    def associative_embedding(self):
        # assoc = getattr(self.fetches.y, "associative", None)
        assoc = self.fields[1][1:3]   # get the vector in the fields
        if assoc is not None:
            assoc = assoc.tanh()
        return assoc

    def seed(self, b=None, **kwargs):
        """predicted seed on every pixel of batch/image/instance"""
        if b is not None:
            return self.seed(**kwargs)[b]
        else:
            # return self.fetches.y.seed.sigmoid()
            return self.fields[1][0].sigmoid()  # confidences

    def ppsigma(self, b=None, *, mask=None):
        """predicted pre-pseudo-sigma on every pixel of batch/image/instance"""

        if mask is not None:
            return self._masked(self.ppsigma(b), mask)
        elif b is not None:
            return self.ppsigma()[b]
        else:
            # ppsigma = self.fetches.y.sigma
            ppsigma = self.fields[3:5]      # get sigmas
            return ppsigma

    def _psigma(self, ppsigma):
        """Convert pre-pseudo-sigma to pseudo-sigma"""
        return torch.exp(10*ppsigma)

    def inst_embedding(self, **kwargs):
        """predicted embedding for instance"""
        return self.embedding( **kwargs).mean(dim=1)

    def inst_ppsigma(self, **kwargs):
        return self.ppsigma(**kwargs).mean(dim=1)

    def gaussian(self, split=False, *, l22n=None, **kwargs):
        """gaussian between pixel and instance embeddings for every pixel"""
        if split:
            spatial_l22n, assoc_l22n = self.l22n(True, **kwargs)
            return self.gaussian(l22n=spatial_l22n), self.gaussian(l22n=assoc_l22n)
        if l22n is None:    l22n = self.l22n(**kwargs)
        return torch.exp(-0.5*l22n)

    def l22n(self, split=False, *, embedding_map=None, centroid=None, psigma=None):
        """l2 square normalized pixel and instance embdding for every pixel"""
        if embedding_map is None:   embedding_map = self.embedding()
        if centroid is None:        centroid = self.inst_embedding()
        if psigma is None:          psigma = self.inst_psigma()
        if split: return [
            self.l22n(embedding_map=embedding_map, centroid=centroid, psigma=psigma)
            for embedding_map, centroid, psigma in
            zip(self.split(embedding_map), self.split(centroid), self.split(psigma))
            ]
        dist = (embedding_map - centroid[:,None,None])**2
        dist = dist * psigma[:,None,None]
        return dist.sum(dim=0,keepdim=True)