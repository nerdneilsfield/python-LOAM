import math
import numpy as np

from utils import matrix_dot_product


class FeatureExtractor:
    # Number of segments to split every scan for feature detection
    N_SEGMENTS = 6

    # Number of less sharp points to pick from point cloud
    PICKED_NUM_LESS_SHARP = 20
    # Number of sharp points to pick from point cloud
    PICKED_NUM_SHARP = 4
    # Number of less sharp points to pick from point cloud
    PICKED_NUM_FLAT = 4
    # Threshold to split sharp and flat points
    SURFACE_CURVATURE_THRESHOLD = 0.1
    # Radius of points for curvature analysis (S / 2 from original paper, 5A section)
    FEATURES_REGION = 5

    def extract_features(self, laser_cloud, scan_start, scan_end):
        keypoints_sharp = []
        keypoints_less_sharp = []
        keypoints_flat = []
        keypoints_less_flat = []

        cloud_curvatures = self.get_curvatures(laser_cloud)

        cloud_label = np.zeros((laser_cloud.shape[0]))
        cloud_neighbors_picked = np.zeros((laser_cloud.shape[0]))

        cloud_neighbors_picked = self.remove_unreliable(
            cloud_neighbors_picked, laser_cloud, scan_start, scan_end)

        for i in range(scan_end.shape[0]):
            s = scan_start[i] + self.FEATURES_REGION
            e = scan_end[i] - self.FEATURES_REGION - 1
            if e - s < self.N_SEGMENTS:
                continue

            for j in range(self.N_SEGMENTS):
                sp = s + (e - s) * j // self.N_SEGMENTS
                ep = s + (e - s) * (j + 1) // self.N_SEGMENTS - 1
                segments_curvatures = cloud_curvatures[sp:ep + 1]
                sort_indices = np.argsort(segments_curvatures)

                largest_picked_num = 0
                for k in reversed(range(ep - sp)):
                    if i < 45:
                        break
                    ind = sort_indices[k] + sp

                    if cloud_neighbors_picked[ind] == 0 and cloud_curvatures[ind] > 0.5 and \
                            self.can_be_edge(laser_cloud, ind):
                        largest_picked_num += 1
                        if largest_picked_num <= self.PICKED_NUM_SHARP:
                            keypoints_sharp.append(laser_cloud[ind])
                            keypoints_less_sharp.append(laser_cloud[ind])
                            cloud_label[ind] = 2
                        elif largest_picked_num <= self.PICKED_NUM_LESS_SHARP:
                            keypoints_less_sharp.append(laser_cloud[ind])
                            cloud_label[ind] = 1
                        else:
                            break

                        cloud_neighbors_picked = self.mark_as_picked(
                            laser_cloud, cloud_neighbors_picked, ind)

                smallest_picked_num = 0
                for k in range(ep - sp):
                    if i < 50:
                        break
                    ind = sort_indices[k] + sp

                    if cloud_neighbors_picked[ind] == 0 and cloud_curvatures[
                            ind] < self.SURFACE_CURVATURE_THRESHOLD:
                        smallest_picked_num += 1
                        cloud_label[ind] = -1
                        keypoints_flat.append(laser_cloud[ind])

                        if smallest_picked_num >= self.PICKED_NUM_FLAT:
                            break

                        cloud_neighbors_picked = self.mark_as_picked(
                            laser_cloud, cloud_neighbors_picked, ind)

                for k in range(sp, ep + 1):
                    if cloud_label[k] <= 0 and cloud_curvatures[k] < self.SURFACE_CURVATURE_THRESHOLD \
                            and not self.has_gap(laser_cloud, k):
                        keypoints_less_flat.append(laser_cloud[k])
        import utils
        import open3d as o3d
        # keypoints = utils.get_pcd_from_numpy(np.vstack(keypoints_less_flat))
        # keypoints.paint_uniform_color([0, 1, 0])
        keypoints_2 = utils.get_pcd_from_numpy(np.vstack(keypoints_flat))
        keypoints_2.paint_uniform_color([1, 0, 0])
        pcd = utils.get_pcd_from_numpy(laser_cloud)
        pcd.paint_uniform_color([0, 0, 1])
        # o3d.visualization.draw_geometries([pcd, keypoints_2])

        return keypoints_sharp, keypoints_less_sharp, keypoints_flat, keypoints_less_flat

    def get_curvatures(self, pcd):
        coef = [1, 1, 1, 1, 1, -10, 1, 1, 1, 1, 1]
        assert len(coef) == 2 * self.FEATURES_REGION + 1
        discr_diff = lambda x: np.convolve(x, coef, 'valid')
        x_diff = discr_diff(pcd[:, 0])
        y_diff = discr_diff(pcd[:, 1])
        z_diff = discr_diff(pcd[:, 2])
        curvatures = x_diff * x_diff + y_diff * y_diff + z_diff * z_diff
        curvatures /= np.linalg.norm(
            pcd[self.FEATURES_REGION:-self.FEATURES_REGION], axis=1) * 10
        curvatures = np.pad(curvatures, self.FEATURES_REGION)
        return curvatures

    def mark_as_picked(self, laser_cloud, cloud_neighbors_picked, ind):
        cloud_neighbors_picked[ind] = 1

        diff_all = laser_cloud[ind - self.FEATURES_REGION + 1:ind + self.FEATURES_REGION + 2] - \
                   laser_cloud[ind - self.FEATURES_REGION:ind + self.FEATURES_REGION + 1]

        sq_dist = matrix_dot_product(diff_all[:, :3], diff_all[:, :3])

        for i in range(1, self.FEATURES_REGION + 1):
            if sq_dist[i + self.FEATURES_REGION] > 0.05:
                break
            cloud_neighbors_picked[ind + i] = 1

        for i in range(-self.FEATURES_REGION, 0):
            if sq_dist[i + self.FEATURES_REGION] > 0.05:
                break
            cloud_neighbors_picked[ind + i] = 1

        return cloud_neighbors_picked

    def remove_unreliable(self, cloud_neighbors_picked, pcd, scan_start,
                          scan_end):
        for i in range(scan_end.shape[0]):
            sp = scan_start[i] + self.FEATURES_REGION
            ep = scan_end[i] - self.FEATURES_REGION

            if ep - sp < self.N_SEGMENTS:
                continue

            for j in range(sp + 1, ep):
                prev_point = pcd[j - 1][:3]
                point = pcd[j][:3]
                next_point = pcd[j + 1][:3]

                diff_next = np.dot(point - next_point, point - next_point)

                if diff_next > 0.1:
                    depth1 = np.linalg.norm(point)
                    depth2 = np.linalg.norm(next_point)

                    if depth1 > depth2:
                        weighted_dist = np.sqrt(
                            np.dot(point - next_point * depth2 / depth1, point
                                   - next_point * depth2 / depth1)) / depth2
                        if weighted_dist < 0.1:
                            cloud_neighbors_picked[j - self.FEATURES_REGION:j +
                                                   1] = 1
                            continue
                    else:
                        weighted_dist = np.sqrt(
                            np.dot(point - next_point * depth1 / depth2, point
                                   - next_point * depth1 / depth2)) / depth1

                        if weighted_dist < 0.1:
                            cloud_neighbors_picked[j - self.FEATURES_REGION:j +
                                                   self.FEATURES_REGION +
                                                   1] = 1
                            continue
                    diff_prev = np.dot(point - prev_point, point - prev_point)
                    dis = np.dot(point, point)

                    if diff_next > 0.0002 * dis and diff_prev > 0.0002 * dis:
                        cloud_neighbors_picked[j] = 1

        return cloud_neighbors_picked

    def has_gap(self, laser_cloud, ind):
        diff_S = laser_cloud[ind - self.FEATURES_REGION:ind +
                             self.FEATURES_REGION +
                             1, :3] - laser_cloud[ind, :3]
        sq_dist = matrix_dot_product(diff_S[:, :3], diff_S[:, :3])
        gapped = sq_dist[sq_dist > 0.3]
        if gapped.shape[0] > 0:
            return True
        else:
            return False

    def can_be_edge(self, laser_cloud, ind):
        diff_S = laser_cloud[ind - self.FEATURES_REGION:ind + self.FEATURES_REGION, :3] -\
                 laser_cloud[ind - self.FEATURES_REGION + 1:ind + self.FEATURES_REGION + 1, :3]
        sq_dist = matrix_dot_product(diff_S[:, :3], diff_S[:, :3])
        gapped = laser_cloud[ind - self.FEATURES_REGION:ind +
                             self.FEATURES_REGION, :3][sq_dist > 0.2]
        if len(gapped) == 0:
            return True
        else:
            return np.any(
                np.linalg.norm(gapped, axis=1) > np.linalg.norm(
                    laser_cloud[ind][:3]))
