import os
import cv2
import math
import logging
import datetime
import numpy as np
from queue import Empty
from multiprocessing import Queue
from typing import Tuple
from scipy.integrate import solve_ivp

    
def config_logging():
    log_dir = 'logs'
    log_filename = f'{log_dir}/{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}.log'
    log_format = '[%(asctime)s][%(levelname)s]%(message)s'

    if not os.path.isdir(log_dir):
        os.mkdir(log_dir)
    logging.basicConfig(format=log_format, filename=log_filename, level=logging.DEBUG)

    formatter = logging.Formatter(log_format)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)


def drawContour(img: cv2.Mat, points, color=(0, 0, 255), thickness=3) -> None:
    points = np.int32(points)
    cv2.drawContours(img, [points], -1, color, thickness)


def drawPoint(img: cv2.Mat, point, color=(0, 0, 255), radius=3, thickness=None) -> None:
    center = np.int32(point)
    if thickness == None:
        cv2.circle(img, center, radius, color, cv2.FILLED)
    else:
        cv2.circle(img, center, radius, color, thickness)


def drawAxis(img, origin, rvec, tvec, cameraMatrix, distCoeffs, scale=30, thickness=3) -> None:
    '''x: blue, y: green, z: red'''
    axisPoints = scale * np.float32([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    origin = np.int32(origin)

    imgPoints, _ = cv2.projectPoints(axisPoints, rvec, tvec, cameraMatrix, distCoeffs)
    imgPoints = np.int32(imgPoints)

    cv2.line(img, origin, imgPoints[2][0], (0, 0, 255), thickness)
    cv2.line(img, origin, imgPoints[0][0], (255, 0, 0), thickness)
    cv2.line(img, origin, imgPoints[1][0], (0, 255, 0), thickness)


def putText(img: cv2.Mat, text: str, point, color=(0, 0, 255), thickness=2) -> None:
    anchor = np.int32(point)
    cv2.putText(img, text, anchor, cv2.FONT_HERSHEY_SIMPLEX, 1, color, thickness)


def getParaTime(pos, bulletSpeed):
    '''
    用抛物线求子弹到目标位置的时间.
    pos:目标的坐标(mm);
    bulletSpeed:子弹速度(m/s);
    return: (ms).
    '''
    pos = np.reshape(pos, (3,))
    x = pos[0]
    y = pos[1]
    z = pos[2]

    dxz = math.sqrt(x*x+z*z)
    a = 0.5*9.7940/1000*dxz*dxz/(bulletSpeed*bulletSpeed)
    b = dxz
    c = a - y

    res1 = (-b + math.sqrt(b**2-4*a*c))/(2*a)
    res2 = (-b - math.sqrt(b**2-4*a*c))/(2*a)

    beta1 = math.atan(res1)
    beta2 = math.atan(res2)

    t1 = dxz/(bulletSpeed*math.cos(beta1))
    t2 = dxz/(bulletSpeed*math.cos(beta2))

    # t = math.sqrt(x**2+y**2+z**2)/bulletSpeed

    t = t1 if t1 < t2 else t2

    return t


def shoot_pitch(x, y, z, bullet_speed) -> float:
    g = 9.794 / 1000
    distance = (x**2 + z**2)**0.5

    a = 0.5 * g * distance**2 / bullet_speed**2
    b = -distance
    c = a - y

    result1 = (-b + math.sqrt(b**2-4*a*c))/(2*a)
    result2 = (-b - math.sqrt(b**2-4*a*c))/(2*a)
    pitch1 = math.atan(result1)
    pitch2 = math.atan(result2)
    t1 = distance / (bullet_speed * math.cos(pitch1))
    t2 = distance / (bullet_speed * math.cos(pitch2))

    pitch = pitch1 if t1 < t2 else pitch2
    pitch = math.degrees(pitch)

    # print(f"calculate gravity -- pitch1: {math.degrees(pitch1)} pitch2: {math.degrees(pitch2)} pitch: {pitch}")

    return pitch


def R_gimbal2imu(yaw: float, pitch: float) -> np.ndarray:
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    R_y = np.array([[math.cos(yaw), 0, math.sin(yaw)],
                    [0, 1, 0],
                    [-math.sin(yaw), 0, math.cos(yaw)]])
    R_x = np.array([[1, 0, 0],
                    [0, math.cos(pitch), -math.sin(pitch)],
                    [0, math.sin(pitch), math.cos(pitch)]])
    return R_y @ R_x


def project_imu2pixel(
        point_in_imu_mm: np.ndarray,
        yaw_degree: float, pitch_degree: float,
        cameraMatrix: np.ndarray, distCoeffs: np.ndarray,
        R_camera2gimbal: np.ndarray, t_camera2gimbal: np.ndarray
) -> np.ndarray:
    R_imu2gimbal = R_gimbal2imu(yaw_degree, pitch_degree).T
    R_gimbal2camera = R_camera2gimbal.T
    point_in_gimbal_mm = R_imu2gimbal @ point_in_imu_mm
    point_in_camera_mm = R_gimbal2camera @ point_in_gimbal_mm - R_gimbal2camera @ t_camera2gimbal
    point_in_pixel, _ = cv2.projectPoints(point_in_camera_mm, np.zeros((3,1)), np.zeros((3,1)), cameraMatrix, distCoeffs)
    point_in_pixel = point_in_pixel[0][0]
    return point_in_pixel


def clear_queue(q: Queue) -> None:
    try:
        while True:
            q.get(timeout=0.1)
    except Empty:
        return
    
    
def limit_rad(angle_rad: float) -> float:
    '''(-pi,pi]'''
    while angle_rad <= -math.pi:
        angle_rad += 2 * math.pi
    while angle_rad > math.pi:
        angle_rad -= 2 * math.pi
    return angle_rad

    
def normalize_angle_positive(angle):
    """ Normalizes the angle to be 0 to 2*pi
        It takes and returns radians. """
    return math.fmod(math.fmod(angle, 2.0*math.pi) + 2.0*math.pi, 2.0*math.pi)

def normalize_angle(angle):
    """ Normalizes the angle to be -pi to +pi
        It takes and returns radians."""
    a = normalize_angle_positive(angle)
    if a > math.pi:
        a -= 2.0 * math.pi
    return a

def shortest_angular_distance(from_angle, to_angle):
    """ Given 2 angles, this returns the shortest angular
        difference.  The inputs and ouputs are of course radians.

        The result would always be -pi <= result <= pi. Adding the result
        to "from" will always get you an equivalent angle to "to".
    """
    return normalize_angle(to_angle - from_angle)

def is_triangle(a, b, c):
    """
    Args:
        xo 自己车中心
        xa 敌方装甲板中心
        xc 敌方车中心
        a (xo 2 xa): 
        b (xo 2 xc): 
        c (xa 2 xc): 
    """
    if a + b > c and a + c > b and b + c > a:
        return True
    else:
        return False

def triangle_angles(a, b, c):
    # 使用余弦定理计算角度
    angle_B = math.degrees(math.acos((a**2 + c**2 - b**2) / (2 * a * c)))
    return (180 - angle_B)

def find_closest_value(x: float, value: Tuple[float, ...]) -> float:
    '''找出x最接近value中的哪个值(限制15%差值)'''
    closest_val = None
    min_diff = float('inf')
    diff = None

    for val in value:
        diff = abs(x - val)
        if diff < min_diff:
            min_diff = diff
            closest_val = val
    
    if diff > (0.4-0.2)*0.15:
        return x
            
    return closest_val

def trajectoryAdjust(target_pos, robot, enableAirRes=1):
    '''
    弹道调整，返回重力（及空气阻力）补偿后的目标位置。

    target_pos: mm;
    pitch_offset: 度;
    robot: 本机;
    enableAirRes: 是否计算空气阻力。

    return: mm。
    '''
    pos = np.reshape(target_pos, (3,))
    x, y, z = pos
    try:
        pitch = shoot_pitch(x, y, z, robot.bullet_speed) # 枪管向上抬为正
    except:
        print("error when calzulate pitch with gravity")
        return None
    
    if enableAirRes==1:
        try:
            # Drag coefficient, projectile radius (m), area (m2) and mass (kg).
            m = 41/1000 if robot.id==1 else 0.0032
            g = 9.794
            # k = 0.00021862500000000002 if robot.id==1 else 6.0896287678629725e-05 # 发光大弹丸/发光小弹丸
            k = 0.00022802630547843214 if robot.id==1 else 6.0896287678629725e-05 # 老的大弹丸/发光小弹丸
            pitch = findPitch(robot.bullet_speed, k, m, g, math.sqrt(x**2+z**2), y, pitch-5, pitch+10)
            
        except:
            print("弹道空气阻力补偿计算出错")
    
    
    armor_in_gun = np.array([x, y, z]).reshape(3, 1)
    armor_in_gun[1] = (x*x + z*z) ** 0.5 * -math.tan(math.radians(pitch))

    return armor_in_gun

def calculateDrop(bulletSpeed, k, m, g, pitch, distance):
    '''
    计算弹丸在空气阻力和重力的作用下下坠距离,返回y坐标(mm)
    
    弹速(m/s); 空气阻力系数; 质量(kg); 重力加速度(m/s2); pitch(度); 水平飞行距离(mm);
    '''
    distanceM = distance/1000 # mm -> m

    v0 = bulletSpeed
    phi0 = np.radians(pitch)   
    u0 = 0, v0 * np.cos(phi0), 0., v0 * np.sin(phi0)
    t0, tf = 0, 10

    def deriv(t, u):
        x, xdot, z, zdot = u
        speed = np.hypot(xdot, zdot)
        xdotdot = -k/m * speed * xdot
        zdotdot = -k/m * speed * zdot - g
        return xdot, xdotdot, zdot, zdotdot

    def hit_target(t, u):
        # We've hit the target if the z-coordinate is 0.
        return u[0]-distanceM
    
    # Stop the integration when we hit the target.
    hit_target.terminal = True
    # We must be moving downwards (don't stop before we begin moving upwards!)
    hit_target.direction = 1

    soln = solve_ivp(deriv, (t0, tf), u0, dense_output=False,
                 events=(hit_target))
    
    y = soln.y_events[0][0][2]
    y = -y*1000 # m -> mm

    return y

def findPitch(bulletSpeed, k, m, g, distance, y, x0, x1, tol=1, maxiter=100):
    '''割线法求解'''
    f0, f1 = y - calculateDrop(bulletSpeed, k, m, g, x0, distance), y - calculateDrop(bulletSpeed, k, m, g, x1, distance)

    for i in range(maxiter):
        if abs(f1) < tol:
            # print("迭代次数:"+str(i))
            return x1
        dfdx = (f1 - f0) / (x1 - x0)
        x2 = x1 - f1 / dfdx
        f0, f1 = f1, y - calculateDrop(bulletSpeed, k, m, g, x2, distance)
        x0, x1 = x1, x2

    raise RuntimeError('Failed to converge')

def printMsgWithTime(msg):
    now = datetime.datetime.now()
    time_now = now.strftime("%H:%M:%S.%f")
    date = now.strftime("%m-%d")
    datetime_str = f"{date} {time_now} "
    print(datetime_str + str(msg))
    
