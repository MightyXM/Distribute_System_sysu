import grpc
import os
import sys
import random
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

# 添加路径
ROOT_PATH = 'D:\myDFS'
sys.path.append(ROOT_PATH)
sys.path.append(ROOT_PATH + '\managementServer')
sys.path.append(ROOT_PATH + '\storageServer')
# 数据服务器rpc
from storageServer import storageServer_pb2 as st_pb2
from storageServer import storageServer_pb2_grpc as st_pb2_grpc
# 管理服务器rpc
from manageServer import manageServer_pb2 as ma_pb2
from manageServer import manageServer_pb2_grpc as ma_pb2_grpc
# 参数文件
import parameter


class Client():
    def __init__(self, id):
        self.id = id
        self.root_path = parameter._ROOT_PATH + '/DATASTORE/client_%d/' % (id)
        self.cur_path = ''
        self.openFile = list()  # 已打开文件列表
        # 创建数据的主文件夹作为用户的缓存
        if not os.path.exists(self.root_path):
            os.mkdir(self.root_path)
        # 连接到管理服务器
        print('Connect with the Management Server ...')
        maChannel = grpc.insecure_channel(parameter._MANAGEMENT_IP + ':' + parameter._MANAGEMENT_PORT)
        self.maStub = ma_pb2_grpc.managementServerStub(maChannel)
        # 选择存储服务器
        self.selectStorageServer()

    def selectStorageServer(self):
        try:
            response = self.maStub.getServerList(ma_pb2.empty(e=1))
            random.seed()
            rand = random.randint(0,len(response.list)-1)
            # 随机给客户一个存储服务器
            server = response.list[rand]
            stChannel = grpc.insecure_channel(str(server.ip)+':'+str(server.port))
            self.stStub = st_pb2_grpc.storageServerStub(stChannel)

            # 这里对用户是透明的，但是为了调试方便打印出来
            self.server_root_path = ROOT_PATH + f'/DATASTORE/storage_%d/'%(server.id)
            print(f'Client {self.id} successfully started and connected with server %d' %(server.id))

        except Exception as e:
            print(e.args)
            print('Client startup failed.Please try again later.')

    def ls(self):
        response = self.stStub.lsall(st_pb2.file_path(path=self.cur_path))
        print(response.list)

    def mkdir(self, fileName):
        response = self.stStub.mkdir(st_pb2.file_path(path=self.cur_path + fileName))
        if response.done:
            print('Successfully create dir:%s.' % fileName)
        else:
            print('Create failed.')

    def rm(self, fileName):
        response = self.stStub.synDelete(st_pb2.file_path(path=self.cur_path + fileName))
        if response.done:
            print('Successfully delete dir:%s.' % fileName)
        else:
            print('Delete failed.')

    def download(self, fileName):
        try:
            response = self.stStub.download(st_pb2.file_path(path=self.cur_path + fileName))
            # 二进制打开文件用于写入
            path = self.root_path + self.cur_path
            # 本地文件不存在就创建
            if not os.path.exists(path):
                os.mkdir(path)
            with open(path + fileName, 'wb') as f:
                for i in response:
                    f.write(i.buffer)
            print('Successfully download the file.')
        except Exception as e:
            print(e.args)
            print('Download failed.')

    def create(self, fileName):
        self.selectStorageServer()
        path = self.root_path + self.cur_path
        # 本地文件不存在就创建
        if not os.path.exists(path):
            os.mkdir(path)
        with open(path + fileName, 'w') as f:
            try:
                while True:
                    msg = input("Enter ctrl+c to exit: ")
                    f.write(msg)
            except KeyboardInterrupt:
                # 结束写入
                f.close()
        # 上传到连接的服务器
        path = path + fileName  # 本地绝对路径
        rPath = self.cur_path + fileName  # 相对路径
        reply = self.stStub.upload(self.getBuffer(rPath, path))
        if(reply.done==1):
            print('Successfully create file:' + fileName)
        # 清空缓存
        if(self.cur_path==''):
            os.remove(path)
        else:
            shutil.rmtree(self.root_path+self.cur_path)

    def update(self,filename):
        try:
            response = self.stStub.ls(st_pb2.file_path(path=self.cur_path))
            if filename in response.list and os.path.isfile(self.server_root_path + self.cur_path + filename):
                # 确定文件存在且是文件而非文件夹
                # 对文件进行上锁
                response = self.maStub.lockFile(ma_pb2.lockInfo(clientId=self.id, filePath=self.cur_path + filename))
                if response.done == 1:
                    # 成功上锁
                    self.openFile.append(self.cur_path + filename)
                    # 下载文件到本地
                    self.download(filename)
                    print('Successfully open: ' + filename)
                    # 输出文件信息
                    print('************FILE CONTENT*************')
                    with open(self.root_path + self.cur_path + filename, 'r') as f:
                        buf = f.read()
                        print(buf)
                    f.close()
                    print('************UPDATE FILE**************')
                    with open(self.root_path + self.cur_path + filename, 'w') as f:
                        try:
                            while True:
                                msg = input("Enter ctrl+c to exit: ")
                                f.write(msg)
                        except KeyboardInterrupt:
                            # 结束写入
                            f.close()
                    print('*************************************')
                    # 广播到所有服务器
                    self.upload(filename)
                else:
                    print(response.info)
            elif filename not in response.list:
                resp = self.maStub.searchFile(ma_pb2.filePath(filePath=self.cur_path + filename))
                if resp.done == 1:
                    prepath = self.server_root_path
                    self.server_root_path = ROOT_PATH + f'/DATASTORE/storage_%d/' % (resp.serverId)
                    response = self.maStub.lockFile(ma_pb2.lockInfo(clientId=self.id, filePath=self.cur_path + filename))
                    if response.done == 1:
                        # 成功上锁
                        self.openFile.append(self.cur_path + filename)
                        # 下载文件到本地
                        self.download(filename)
                        print('Successfully open: ' + filename)
                        # 输出文件信息
                        print('************FILE CONTENT*************')
                        with open(self.root_path + self.cur_path + filename, 'r') as f:
                            buf = f.read()
                            print(buf)
                        f.close()
                        print('************UPDATE FILE**************')
                        with open(self.root_path + self.cur_path + filename, 'w') as f:
                            try:
                                while True:
                                    msg = input("Enter ctrl+c to exit: ")
                                    f.write(msg)
                            except KeyboardInterrupt:
                                # 结束写入
                                f.close()
                        print('*************************************')
                        # 广播到所有服务器
                        self.upload(filename)
                    else:
                        print(response.info)
                self.server_root_path = prepath
            else:
                print('Can`t find this file.')
        except Exception:
            print('no file')
    def getBuffer(self, rPath, path):
        # 根据文件相对路径和本地绝对路径返回流式数据
        with open(path, 'rb') as f:
            buf = f.read(parameter._BUFFER_SIZE)
            yield st_pb2.upload_file(path=rPath, buffer=buf)

    def upload(self, fileName):
        try:
            path = self.root_path + self.cur_path + fileName  # 本地绝对路径
            rPath = self.cur_path + fileName  # 相对路径
            if os.path.exists(path):
                response = self.stStub.synUpload(self.getBuffer(rPath, path))
                print('Successfully upload the file.')
            else:
                print('Can`t find this file.')
        except Exception as e:
            print(e.args)
            print('Upload failed.')

    def cd(self, fold):
        response = self.stStub.ls(st_pb2.file_path(path=self.cur_path))
        path = self.server_root_path + self.cur_path + fold
        try:
            if fold in response.list and os.path.isdir(path):
                # 成功进入文件夹
                self.cur_path += fold + '/'
            elif fold not in response.list:
                re = self.maStub.searchFile(ma_pb2.filePath(filePath=self.cur_path+fold))
                if re.done == 1:
                    self.mkdir(fold)
                    self.cur_path += fold + '/'
                else:
                    print('Can`t enter this fold')
            else:
                print('Can`t enter this fold')
        except Exception:
            print("Fold is no exits")


    def cdBack(self):
        if (self.cur_path != ''):
            self.cur_path = os.path.dirname(self.cur_path[:-1]) + '/'
            if self.cur_path == '/':
                self.cur_path = ''
        else:
            print('Alreay in root dir.')

    def open(self, fileName):
        try:
            response = self.stStub.ls(st_pb2.file_path(path=self.cur_path))
            if fileName in response.list and os.path.isfile(self.server_root_path + self.cur_path + fileName):
                # 确定文件存在且是文件而非文件夹
                # 对文件进行上锁
                response = self.maStub.lockFile(ma_pb2.lockInfo(clientId=self.id, filePath=self.cur_path + fileName))
                if response.done == 1:
                    # 成功上锁
                    self.openFile.append(self.cur_path + fileName)
                    # 下载文件到本地
                    self.download(fileName)
                    print('Successfully open: ' + fileName)
                    # 输出文件信息
                    print('************FILE CONTENT*************')
                    with open(self.root_path + self.cur_path + fileName, 'r') as f:
                        buf = f.read()
                        print(buf)
                    f.close()
                    print('*************************************')
                else:
                    print(response.info)
            elif fileName not in response.list:
                response = self.maStub.searchFile(ma_pb2.filePath(filePath=self.cur_path + fileName))
                if response.done==1:
                    prepath = self.server_root_path
                    self.server_root_path = ROOT_PATH + f'/DATASTORE/storage_%d/' % (response.serverId)
                    if(os.path.isfile(self.server_root_path + self.cur_path + fileName)):
                        response = self.maStub.lockFile(ma_pb2.lockInfo(clientId=self.id, filePath=self.cur_path + fileName))
                        if response.done == 1:
                            # 成功上锁
                            self.openFile.append(self.cur_path + fileName)
                            # 下载文件到本地
                            self.download(fileName)
                            print('Successfully open: ' + fileName)
                            # 输出文件信息
                            print('************FILE CONTENT*************')
                            with open(self.root_path + self.cur_path + fileName, 'r') as f:
                                buf = f.read()
                                print(buf)
                            f.close()
                            print('*************************************')
                        else:
                            print(response.info)
                        self.server_root_path = prepath
                else:
                    print("no file.")
        except Exception:
            print("no file.")

    def close(self, fileName):
        path = self.cur_path + fileName
        if path in self.openFile:
            self.openFile.remove(path)
            # 上传文件
            # self.upload(fileName)
            # 解锁文件
            response = self.maStub.unlockFile(ma_pb2.lockInfo(clientId=self.id, filePath=self.cur_path + fileName))
            if response.done == 1:
                if(self.cur_path == ''):
                    os.remove(self.root_path + fileName)
                else:
                    shutil.rmtree(self.root_path+self.cur_path)
                # os.remove(self.root_path + self.cur_path + fileName)
                print('Successfully close: ' + fileName)
            else:
                print(response.info)
        else:
            print('You haven`t open this file.')

    def help(self):
        print('Client ID: %d' % (self.id))
        print("-------------------- COMMAND LIST --------------------")
        print("ls       : List file directories")
        print("cd       : Change current path")
        print("cd..     : Go back to the previous path")
        print("create   : Create files locally")
        print("open     : Open files")
        print("close    : Close files")
        print("mkdir    : Create a folder")
        print("rm       : Delete files")
        print("update   : Update files")
        print("------------------------------------------------------")


# 启动客户端
def startClient(id):
    client = Client(id)
    while True:
        print('$' + client.cur_path + '>', end=' ')
        command = input().split()
        if not command:
            continue
        elif command[0] == 'help':
            client.help()
        elif command[0] == 'ls':
            client.ls()
        elif command[0] == 'cd..':
            client.cdBack()
        elif command[0] == 'cd':
            if len(command) == 2:
                client.cd(command[1])
            else:
                print("Usage: cd <directory>")
        elif command[0] == 'rm':
            if len(command) == 2:
                client.rm(command[1])
            else:
                print("Usage: rm <filename>")
        elif command[0] == 'mkdir':
            if len(command) == 2:
                client.mkdir(command[1])
            else:
                print("Usage: mkdir <directory>")
        elif command[0] == 'open':
            if len(command) == 2:
                client.open(command[1])
            else:
                print("Usage: open <filename>")
        elif command[0] == 'close':
            if len(command) == 2:
                client.close(command[1])
            else:
                print("Usage: close <filename>")
        elif command[0] == 'create':
            if len(command) == 2:
                client.create(command[1])
            else:
                print("Usage: create <filename>")
        elif command[0] == 'update':
            if(len(command)) == 2:
                client.update(command[1])
            else:
                print("Usage: update <filename>")
        else:
            print("Cannot understand, please check your command.")
            client.help()


if __name__ == "__main__":
    # 执行时输入客户端id: python3 client.py arg_id
    random.seed()
    clientId = random.randint(1,5)
    startClient(clientId)