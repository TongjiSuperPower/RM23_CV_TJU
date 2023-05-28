import numpy as np

cameraMatrix = np.float32([[2709.404579882423, 0.0, 632.4531176080411], [0.0, 2709.7190039316306, 497.5549078080179], [0.0, 0.0, 1.0]])
distCoeffs = np.float32([-0.6198594308482569, 1.6064217414065494, -0.0022930662669893346, 0.0027075289631306376, -7.753661179852058])
R_camera2gimbal = np.float32([[0.999864397938302, -0.0021621045289270005, 0.01632516583325252], [0.0014649965017206272, 0.9990914206945056, 0.04259327270689983], [-0.016402424233239076, -0.042563580660470585, 0.9989591093136057]])
t_camera2gimbal = np.float32([[1.3169614461127903], [-47.84255579172414], [195.20987319563574]])
# 重投影误差: 0.0081px
# 相机相对于云台: yaw=0.94 pitch=-2.44 roll=0.08

gun_up_degree = 4.5
gun_right_degree = 0.1
