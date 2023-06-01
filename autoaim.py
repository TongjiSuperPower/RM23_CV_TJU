import sys
import cv2
import math
import time
import logging
import numpy as np

import modules.tools as tools
from modules.io.robot import Robot
from modules.io.recorder import Recorder
from modules.io.communication import Communicator
from modules.autoaim.armor_solver import ArmorSolver
from modules.autoaim.armor_detector import ArmorDetector, is_armor, is_lightbar, is_lightbar_pair
from modules.autoaim.tracker import Tracker

from remote_visualizer import Visualizer


robot_id = 3
enemy_color = 'red'
# enemy_color = 'blue'

exposure_ms = 3
port = '/dev/ttyUSB0'


if __name__ == '__main__':
    tools.config_logging()
    
    enable = False
    if len(sys.argv) > 1:
        enable = (sys.argv[1] == '-y')

    with Communicator(port):
        # 这里的作用是在程序正式运行前，打开串口再关闭。
        # 因为每次开机后第一次打开串口，其输出全都是0，原因未知。
        pass

    try:
        with Robot(exposure_ms, port) as robot, Visualizer(enable=enable) as visualizer, Recorder() as recorder:

            if robot_id == 1:
                from configs.hero import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot_id == 3:
                from configs.infantry3 import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot_id == 4:
                from configs.infantry4 import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot_id == 5:
                from configs.infantry5 import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot_id == 7:
                from configs.sentry import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist

            armor_detector = ArmorDetector(enemy_color)

            armor_solver = ArmorSolver(cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal)

            tracker = Tracker()

            while True:
                time.sleep(1e-4)

                robot.update()

                img = robot.img
                img_time_s = robot.img_time_s

                armors = armor_detector.detect(img)

                yaw_degree, pitch_degree = robot.yaw_pitch_degree_at(img_time_s)
                
                armors = armor_solver.solve(armors, yaw_degree, pitch_degree)
                armors = filter(lambda a: a.name not in whitelist, armors)

                recorder.record(img, (img_time_s, yaw_degree, pitch_degree, robot.bullet_speed, robot.flag))

                # print(f'Tracker state: {tracker.state} ')

                if tracker.state == 'LOST':
                    tracker.init(armors, img_time_s)
                else:
                    tracker.update(armors, img_time_s)

                if tracker.state in ('TRACKING', 'TEMP_LOST'):
                    target = tracker.target
                    try:
                        aim_point_in_imu_m, fire_time_s = target.aim(robot.bullet_speed)
                        robot.shoot(gun_up_degree, gun_right_degree, aim_point_in_imu_m, fire_time_s)
                    except Exception as e:
                        logging.exception(e)

                # 调试分割线

                if not visualizer.enable:
                    continue

                # drawing = img.copy()
                drawing = cv2.convertScaleAbs(img, alpha=5)

                for i, l in enumerate(armor_detector._raw_lightbars):
                    if not is_lightbar(l):
                        continue
                    tools.drawContour(drawing, l.points, (0, 255, 255), 10)

                # for i, lp in enumerate(armor_detector._raw_lightbar_pairs):
                #     if not is_lightbar_pair(lp):
                #         continue
                #     tools.drawContour(drawing, lp.points, (0, 255, 255), 1)
                #     tools.putText(drawing, f'{lp.angle:.2f}', lp.left.top, (255, 255, 255))

                for i, a in enumerate(armor_detector._raw_armors):
                    if not is_armor(a):
                        continue
                    tools.drawContour(drawing, a.points)
                    tools.drawAxis(drawing, a.center, a.rvec, a.tvec, cameraMatrix, distCoeffs)
                    tools.putText(drawing, f'{i} {a.color} {a.name} {a.confidence:.2f}', a.left.top, (255, 255, 255))
                    
                    # cx, cy, cz = a.in_camera_mm.T[0]
                    # tools.putText(drawing, f'cx{cx:.1f} cy{cy:.1f} cz{cz:.1f}', a.left.bottom, (255, 255, 255))

                if tracker.state == 'TRACKING':
                    target = tracker.target

                    messured_yaw = target._last_z_yaw[0, 0]

                    if tracker._target_name == 'small_outpost':
                        xc, yc, zc, target_yaw, w = target._ekf.x.T[0]
                        center_in_imu_m = np.float64([[xc, yc, zc]]).T

                        center_in_pixel = tools.project_imu2pixel(
                            center_in_imu_m * 1e3,
                            yaw_degree, pitch_degree,
                            cameraMatrix, distCoeffs,
                            R_camera2gimbal, t_camera2gimbal
                        )
                        tools.drawPoint(drawing, center_in_pixel, (0, 255, 255), radius=10)
                        tools.putText(drawing, f'{w:.2f}', center_in_pixel, (255, 255, 255))

                        visualizer.plot((target_yaw, messured_yaw, w), ('yaw', 'm_yaw', 'w'))

                    else:
                        x_in_imu, _, y_in_imu, _, z_in_imu, _ = target._ekf.x.T[0]

                    
                    for i, armor_in_imu_m in enumerate(tracker.target.get_all_armor_positions_m()):
                        armor_in_imu_mm = armor_in_imu_m * 1e3
                        armor_in_pixel = tools.project_imu2pixel(
                            armor_in_imu_mm,
                            yaw_degree, pitch_degree,
                            cameraMatrix, distCoeffs,
                            R_camera2gimbal, t_camera2gimbal
                        )
                        tools.drawPoint(drawing, armor_in_pixel, (0, 0, 255), radius=10)

                visualizer.show(drawing)

    except Exception as e:
        logging.exception(e)
