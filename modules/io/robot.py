import cv2
import math
import logging
import numpy as np
from enum import IntEnum
from modules.ekf import ColumnVector
from modules.io.parallel_camera import ParallelCamera
from modules.io.parallel_rx_communicator import ParallelRxCommunicator
from modules.io.parallel_tx_communicator import ParallelTxCommunicator
from modules.io.context_manager import ContextManager
from modules.io.communication import Status, TX_FLAG_FIRE


class WorkMode(IntEnum):
    AUTOAIM = 1
    SMALLNASHOR = 2
    BIGNASHOR = 3


def limit_degree(angle_degree: float) -> float:
    '''(-180,180]'''
    while angle_degree <= -180:
        angle_degree += 360
    while angle_degree > 180:
        angle_degree -= 360
    return angle_degree


def interpolate_degree(from_degree: float, to_degree: float, k: float) -> float:
    delta_degree = limit_degree(to_degree - from_degree)
    result_degree = limit_degree(k * delta_degree + from_degree)
    return result_degree


class Robot(ContextManager):
    def __init__(self, exposure_ms: float, port: str) -> None:
        self._camera = ParallelCamera(exposure_ms)
        self._rx_communicator = ParallelRxCommunicator(port)
        self._tx_communicator = ParallelTxCommunicator(port)

        self.img: cv2.Mat = None
        self.img_time_s: float = None
        self.bullet_speed: float = None
        self.flag: int = None
        self.color: str = None
        self.id: int = None
        self.work_mode = WorkMode.AUTOAIM

    def _close(self) -> None:
        self._camera._close()
        self._rx_communicator._close()
        self._tx_communicator._close()
        logging.info('Robot closed.')

    def update(self):
        '''注意阻塞'''
        self._camera.update()
        self.img = self._camera.img
        self.img_time_s = self._camera.read_time_s

        self._rx_communicator.update()
        _, _, _, bullet_speed, flag = self._rx_communicator.latest_status
        self.bullet_speed = bullet_speed if bullet_speed > 5 else 15

        # flag:
        # 个位: 1:英雄 2:工程 3/4/5:步兵 6:无人机 7:哨兵 8:飞镖 9:雷达站
        # 十位: TODO 用来切换自瞄/能量机关 1:自瞄 2:能量机关
        # 百位: 0:我方为红方 1:我方为蓝方
        self.flag = flag
        self.color = 'red' if self.flag < 100 else 'blue'
        self.id = self.flag % 10
        workModeFlag = (self.flag/10) % 10
        if workModeFlag == 2:
            self.work_mode = WorkMode.SMALLNASHOR
        elif workModeFlag == 3:
            self.work_mode = WorkMode.BIGNASHOR
        else:
            self.work_mode = WorkMode.BIGNASHOR

    def yaw_pitch_degree_at(self, time_s: float) -> tuple[float, float]:
        '''注意阻塞'''
        while self._rx_communicator.latest_read_time_s < time_s:
            self._rx_communicator.update()

        status_before: Status = None
        for read_time_s, status in reversed(self._rx_communicator.history):
            if read_time_s < time_s:
                time_s_before, status_before = read_time_s, status
                break
            time_s_after, status_after = read_time_s, status

        _, yaw_degree_after, pitch_degree_after, _, _, = status_after

        if status_before is None:
            return yaw_degree_after, pitch_degree_after

        _, yaw_degree_before, pitch_degree_before, _, _, = status_before

        k = (time_s - time_s_before) / (time_s_after - time_s_before)
        yaw_degree = interpolate_degree(yaw_degree_before, yaw_degree_after, k)
        pitch_degree = interpolate_degree(pitch_degree_before, pitch_degree_after, k)

        return yaw_degree, pitch_degree

    def shoot(self, gun_up_degree: float, gun_right_degree: float, aim_point_in_imu_m: ColumnVector, fire_time_s: float | None = None) -> None:
        yaw = math.radians(gun_right_degree)
        R_y = np.array([[math.cos(yaw), 0, math.sin(yaw)],
                        [0, 1, 0],
                        [-math.sin(yaw), 0, math.cos(yaw)]])
        
        aim_point_in_imu_m = R_y @ aim_point_in_imu_m

        aim_point_in_imu_mm = aim_point_in_imu_m * 1e3
        x_in_imu_mm, y_in_imu_mm, z_in_imu_mm = aim_point_in_imu_mm.T[0]

        gun_up_rad = math.radians(gun_up_degree)
        distance_mm = (x_in_imu_mm**2 + z_in_imu_mm**2)**0.5
        aim_pitch_rad = math.atan(-y_in_imu_mm/distance_mm)
        y_in_imu_mm = -distance_mm * math.tan(aim_pitch_rad + gun_up_rad)

        if fire_time_s == 0:
            self._tx_communicator.send(x_in_imu_mm, y_in_imu_mm, z_in_imu_mm, flag=TX_FLAG_FIRE)
        else:
            self._tx_communicator.send(x_in_imu_mm, y_in_imu_mm, z_in_imu_mm, fire_time_s=fire_time_s)
