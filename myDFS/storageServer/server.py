import grpc
import os
import sys
import time
import random
import shutil
from concurrent.futures import ThreadPoolExecutor

# 添加路径
ROOT_PATH = 'D:\myDFS'
sys.path.append(ROOT_PATH)
sys.path.append(ROOT_PATH + '\managementServer')
# 数据服务器rpc
import storageServer_pb2 as st_pb2
import storageServer_pb2_grpc as st_pb2_grpc
# 管理服务器rpc
from manageServer import manageServer_pb2 as ma_pb2
from manageServer import manageServer_pb2_grpc as ma_pb2_grpc
# 参数文件
import parameter

class stServer(st_pb2_grpc.storageServerServicer):
    def __init__(self, id, ip, port):
        self.id = id
        self.ip = ip
        self.port = port
        self.root_path = parameter._ROOT_PATH + '/DATASTORE/storage_%d/' % (id)
        self.managementStub = ma_pb2_grpc.managementServerStub(grpc.insecure_channel(parameter._MANAGEMENT_IP + ':' + parameter._MANAGEMENT_PORT))
        # 创建数据的主文件夹
        if not os.path.exists(self.root_path):
            os.mkdir(self.root_path)
        # 存储服务器上线
        self.online()
    def online(self):
        # 每一个存储服务器上线要向管理服务器登记注册
        print('connect with the Management Server ...')
        managementChannel = grpc.insecure_channel(parameter._MANAGEMENT_IP + ':' + parameter._MANAGEMENT_PORT)
        self.managementStub = ma_pb2_grpc.managementServerStub(managementChannel)
        self.managementStub.serverOnline(ma_pb2.serverInfo(id=self.id, ip=self.ip, port=self.port))
        print('Storage Server %d is online' % self.id)

    def offline(self):
        # 向管理服务器登记注销
        self.managementStub.serverOffline(ma_pb2.serverId(id=self.id))
        print('Storage Server %d is offline' % self.id)

    def getBuffer(self, rPath, path):
        # 根据文件相对路径和本地绝对路径返回流式数据
        with open(path, 'rb') as f:
            buf = f.read(parameter._BUFFER_SIZE)
            yield st_pb2.upload_file(path=rPath, buffer=buf)

    def synUpload(self, request, context):
        # 客户端提供文件路径、文件流，服务器更新并同步副本
        try:
            finish = 1
            for iter in request:
                filePath = iter.path
                print('upload: ' + filePath)
                # 二进制打开文件用于写入
                path = os.path.dirname(self.root_path + filePath)
                if not os.path.exists(path):
                    os.mkdir(path)
                with open(self.root_path + filePath, 'wb') as f:
                    f.write(iter.buffer)
            # 把文件广播到其他数据服务器进行同步，保存副本
            # 获取其他服务器信息
            response = self.managementStub.getServerList(ma_pb2.empty(e=1))
            # 遍历其他服务器上传文件
            for server in response.list:
                if server.id != self.id:
                    channel = grpc.insecure_channel(str(server.ip) + ':' + str(server.port))
                    stub = st_pb2_grpc.storageServerStub(channel)
                    stub.upload(self.getBuffer(filePath, self.root_path + filePath))
            print('Successfully uploaded and synchronized the file')
        except Exception as e:
            print(e.args)
            finish = 0
        return st_pb2.reply(done=finish)

    def upload(self, request, context):
        # 提供文件路径、文件流，服务器更新
        try:
            finish = 1
            for iter in request:
                filePath = iter.path
                print('upload: ' + filePath)
                # 二进制打开文件用于写入
                path = os.path.dirname(self.root_path + filePath)
                if not os.path.exists(path):
                    os.mkdir(path)
                with open(self.root_path + filePath, 'wb') as f:
                    f.write(iter.buffer)
            respone = self.managementStub.addFile(ma_pb2.fileInfo(rootPath=self.root_path,serverId=self.id,filePath=filePath))
            if respone.done == 1:
                print('Successfully uploaded the file')
            else:
                print('Error add')
        except Exception as e:
            print(e.args)
            finish = 0
        return st_pb2.reply(done=finish)

    def download(self, request, context):
        # 客户端从服务器下载文件
        respone = self.managementStub.searchFile(ma_pb2.filePath(filePath=request.path))
        if respone.done==1:
            filePath = self.root_path + request.path
            print('download: ' + request.path)
            # 检查文件是否存在
            if os.path.exists(filePath):
                with open(filePath, 'rb') as f:
                    buf = f.read(parameter._BUFFER_SIZE)
                    yield st_pb2.fileStream(buffer=buf)
            else:
                filePath = respone.path+request.path
                with open(filePath, 'rb') as f:
                    buf = f.read(parameter._BUFFER_SIZE)
                    yield st_pb2.fileStream(buffer=buf)

    def ls(self, request, context):
        # 客户端向服务器查询当前目录
        filePath = self.root_path + request.path
        try:
            dirList = ' '.join(os.listdir(filePath))
        except Exception as e:
            return st_pb2.fileList(list='null')
        return st_pb2.fileList(list=dirList)

    def lsall(self,request,context):
        filelist = os.listdir(self.root_path + request.path)
        response = self.managementStub.getServerList(ma_pb2.empty(e=1))
        for server in response.list:
            if server.id != self.id:
                channel = grpc.insecure_channel(str(server.ip) + ':' + str(server.port))
                stub = st_pb2_grpc.storageServerStub(channel)
                resp = stub.ls(st_pb2.file_path(path=request.path))
                # 所有取并集
                if(resp.list!='null'):
                    filelist = list(set(filelist) | set(resp.list.split(' ')))
                else:
                    continue
        filelist.sort()
        filelist = ' '.join(filelist)
        # print(filelist)
        return st_pb2.fileList(list=filelist)

    def mkdir(self, request, context):
        # 客户端要求创建文件夹
        try:
            finish = 1
            filePath = self.root_path + request.path
            # print(filePath)
            respone = self.managementStub.addFile(ma_pb2.fileInfo(rootPath=filePath, serverId=self.id, filePath=request.path))
            if not os.path.exists(filePath):
                os.mkdir(filePath)
        except Exception as e:
            print(e.args)
            finish = 0
        return st_pb2.reply(done=finish)

    def synDelete(self, request, context):
        # 客户端删除服务器文件并同步
        try:
            finish = 1
            filePath = self.root_path + request.path
            if os.path.exists(filePath):
                # self.delete(request,context)
                try:
                    os.remove(filePath)
                    print('Successfully deleted the file')
                except Exception as e:
                    try:
                        shutil.rmtree(filePath)
                        print('Successfully deleted the file')
                    except Exception as e:
                        print('delect failed')
                # 把删除命令广播到其他数据服务器进行同步
                # 获取其他服务器信息
            response = self.managementStub.getServerList(ma_pb2.empty(e=1))
            # 删除管理服务器中的文件表信息
            re = self.managementStub.delectFile(ma_pb2.filePath(filePath=request.path))
            # 遍历其他服务器删除文件
            for server in response.list:
                if server.id != self.id:
                    channel = grpc.insecure_channel(str(server.ip) + ':' + str(server.port))
                    stub = st_pb2_grpc.storageServerStub(channel)
                    stub.delete(st_pb2.file_path(path=request.path))
            print('Successfully deleted the file and synchronized')
        except Exception as e:
            print(e.args)
            finish = 0
        return st_pb2.reply(done=finish)

    def delete(self, request, context):
        # 删除服务器文件
        try:
            finish = 1
            filePath = self.root_path + request.path
            if os.path.exists(filePath):
                try:
                    os.remove(filePath)
                    print('Successfully deleted the file')
                except Exception as e:
                    try:
                        shutil.rmtree(filePath)
                        print('Successfully deleted the file')
                    except Exception as e:
                        print('delect failed')
            else:
                print('invild path.')
        except Exception as e:
            print(e.args)
            finish = 0
        return st_pb2.reply(done=finish)

# 启动服务器
def startServer(id, ip, port):
    st_server = stServer(id, ip, port)
    server = grpc.server(ThreadPoolExecutor(max_workers=3))
    st_pb2_grpc.add_storageServerServicer_to_server(st_server, server)
    server.add_insecure_port(str(ip) + ':' + str(port))
    server.start()
    try:
        while True:
            time.sleep(parameter._ONE_DAY_IN_SECONDS)
    except KeyboardInterrupt:
        # 服务器下线，通知管理服务器
        st_server.offline()
        server.stop(0)


if __name__ == "__main__":
    # 执行时输入服务器id: python3 server.py arg_id
    serverId = int(sys.argv[1])
    serverPort = serverId + 8001
    # 文件服务器端口号为8001+id号，与管理服务器端口错开
    startServer(serverId, 'localhost', serverPort)