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
from modules.Nahsor.nahsor_tracker import NahsorTracker 
from modules.autoaim.tracker import Tracker

from remote_visualizer import Visualizer


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
            robot.update()

            if robot.id == 1:
                from configs.hero import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot.id == 3:
                from configs.infantry3 import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot.id == 4:
                from configs.infantry4 import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist
            elif robot.id == 7:
                from configs.sentry import cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal, gun_up_degree, gun_right_degree, whitelist

            enemy_color = 'red' if robot.color == 'blue' else 'blue'
            armor_detector = ArmorDetector(enemy_color)

            armor_solver = ArmorSolver(cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal)

            tracker = Tracker()

            nahsor_tracker = NahsorTracker(robot_color=robot.color)

            while True:
                time.sleep(1e-4)

                robot.update()

                img = robot.img
                img_time_s = robot.img_time_s

                yaw_degree, pitch_degree = robot.yaw_pitch_degree_at(img_time_s)                

                recorder.record(img, (img_time_s, yaw_degree, pitch_degree, robot.bullet_speed, robot.flag))

                if robot.work_mode == 2 or robot.work_mode == 3:                    
                    # 能量机关模式
                    nahsor_tracker.update(frame=img, robot_work_mode = robot.work_mode)

                    try:
                        target = nahsor_tracker.nahsor
                        predictedPtsInWorld = nahsor_tracker.getShotPoint(0.15, robot.bullet_speed, 
                                                                  R_camera2gimbal, t_camera2gimbal, 
                                                                  cameraMatrix, distCoeffs, 
                                                                  yaw_degree, pitch_degree
                                                                  )
                        
                        if predictedPtsInWorld is not None:                         
                            prepts = np.reshape(predictedPtsInWorld, (3,))
                            p_x = predictedPtsInWorld[0]
                            p_y = predictedPtsInWorld[1]
                            p_z = predictedPtsInWorld[2]
                            p_distance = (p_x**2 + p_z**2)**0.5
                            if p_distance>8500 or p_distance<5000:
                                logging.info(f"nahsor distance error--p_distance = {p_distance}")   
                                armor_in_gun = None                             
                            else:                        
                                armor_in_gun = tools.trajectoryAdjust(predictedPtsInWorld, robot, enableAirRes=0)                   
                                if armor_in_gun is not None:                        
                                    robot.shoot(gun_up_degree, gun_right_degree, armor_in_gun/1000)

                    except Exception as e:
                        logging.exception(e)
                
                else :
                    # 自瞄模式                 
                    nahsor_tracker = NahsorTracker(robot_color=robot.color)

                    armors = armor_detector.detect(img)
                    
                    armors = armor_solver.solve(armors, yaw_degree, pitch_degree)
                    armors = filter(lambda a: a.name not in whitelist, armors)
                    
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
                    # print(f'Tracker state: {tracker.state} ')                
                    

                # 调试分割线---------------------------------------------------------

                if not visualizer.enable:
                    continue

                # drawing = img.copy()
                img = nahsor_tracker.nahsor.show_img
                if img is None:
                    continue
                drawing = cv2.convertScaleAbs(img, alpha=5)

                if robot.work_mode != 2 and robot.work_mode !=3:
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

                    if tracker.state in ('TRACKING', 'TEMP_LOST'):
                        target = tracker.target

                        messured_yaw = target._last_z_yaw[0, 0]

                        if tracker._target_name == 'small_outpost':
                            xc, yc, zc, target_yaw, w = target._ekf.x.T[0]
                            center_in_imu_m = np.float64([[xc, yc, zc]]).T

                            visualizer.plot((target_yaw, messured_yaw, w), ('yaw', 'm_yaw', 'w'))

                        else:
                            xc, yc1, yc2, zc, target_yaw, r1, r2, vx, vy, vz, w = target._ekf.x.T[0]
                            center_in_imu_m = np.float64([[xc, yc1, zc]]).T

                        center_in_pixel = tools.project_imu2pixel(
                            center_in_imu_m * 1e3,
                            yaw_degree, pitch_degree,
                            cameraMatrix, distCoeffs,
                            R_camera2gimbal, t_camera2gimbal
                        )
                        tools.drawPoint(drawing, center_in_pixel, (0, 255, 255), radius=10)
                        tools.putText(drawing, f'{w:.2f}', center_in_pixel, (255, 255, 255))
                        
                        for i, armor_in_imu_m in enumerate(tracker.target.get_all_armor_positions_m()):
                            armor_in_imu_mm = armor_in_imu_m * 1e3
                            armor_in_pixel = tools.project_imu2pixel(
                                armor_in_imu_mm,
                                yaw_degree, pitch_degree,
                                cameraMatrix, distCoeffs,
                                R_camera2gimbal, t_camera2gimbal
                            )
                            tools.drawPoint(drawing, armor_in_pixel, (0, 0, 255), radius=10)
                
                else:
                    if predictedPtsInWorld is not None and armor_in_gun is not None:  
                        current_point_in_pixel = tools.project_imu2pixel(predictedPtsInWorld, yaw_degree, 
                                                                        pitch_degree, cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal)
                        shot_point_in_pixel = tools.project_imu2pixel(armor_in_gun, yaw_degree, 
                                                                        pitch_degree, cameraMatrix, distCoeffs, R_camera2gimbal, t_camera2gimbal)
                        tools.drawPoint(drawing, current_point_in_pixel, (0,255,0))
                        tools.drawPoint(drawing, shot_point_in_pixel, (0,0,255))
                visualizer.show(drawing)

    except Exception as e:
        logging.exception(e)
