import datetime
import parent_folder
from modules.io.mindvision import Camera
from remote_visualizer import Visualizer

if __name__ == '__main__':
    enable: str = None
    while True:
        enable = input('开启Visualizer?输入[y/n]\n')
        if enable == 'y' or enable == 'n':
            break
        else:
            print('请重新输入')
    enable = True if enable == 'y' else False

    with Camera(4) as camera, Visualizer(enable=enable) as visualizer:
        last_read_time_s = 0
        while True:
            success, img = camera.read()
            if not success:
                print('Read failed!')
                break

            print(f'{datetime.datetime.now()} {(camera.read_time_s - last_read_time_s)*1e3:.2f}ms')
            last_read_time_s = camera.read_time_s

            visualizer.show(img)
