# https://github.com/Longdh57/fastapi-minio

from app.utils.uuid6 import uuid7
from datetime import timedelta
from minio import Minio
from pydantic import BaseModel
import os
from urllib.parse import urlparse


class IMinioResponse(BaseModel):
    bucket_name: str
    file_name: str
    url: str


class MinioClient:
    @staticmethod
    def _normalize_endpoint(url_str: str) -> tuple[str, bool]:
        """
        标准化 MinIO 端点字符串：
        - 支持 'http(s)://host[:port]' 或 'host[:port]'
        - 返回 (endpoint, secure)，其中 endpoint 为 'host:port'，secure 指示是否 https
        """
        secure = False
        endpoint = url_str
        try:
            parsed = urlparse(url_str)
            if parsed.scheme in ("http", "https"):
                secure = parsed.scheme == "https"
                endpoint = parsed.netloc or parsed.path
                if ":" not in endpoint:
                    # 未提供端口则根据协议给出默认端口（供直连/反代场景使用）
                    endpoint = f"{endpoint}:443" if secure else f"{endpoint}:80"
        except Exception:
            # 兜底：保持原始字符串与 secure=False
            pass
        return endpoint, secure

    def __init__(
        self, minio_url: str, access_key: str, secret_key: str, bucket_name: str, internal_url: str | None = None
    ):
        # public: 用于生成对外可访问的预签名 URL（不发起网络请求，仅本地签名）
        # internal: 用于容器内与 MinIO 实际通信（上传/下载/删除）
        self.minio_url = minio_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name

        # 内部连通端点优先读取 MINIO_INTERNAL_URL，否则默认使用 docker-compose 服务名
        internal_url = internal_url or os.getenv("MINIO_INTERNAL_URL", "minio_server:9000")
        public_endpoint, public_secure = self._normalize_endpoint(self.minio_url)
        internal_endpoint, internal_secure = self._normalize_endpoint(internal_url)

        # 记录内部端点与候选（用于回退）
        self._internal_endpoint = internal_endpoint
        self._internal_secure = internal_secure
        self._internal_candidates: list[tuple[str, bool]] = [
            (internal_endpoint, internal_secure),
            ("minio_server:9000", False),
            ("minio:9000", False),
            ("localhost:9000", False),
            ("127.0.0.1:9000", False),
        ]
        # 从 MINIO_URL 派生一个 host:9000 作为候选（若有 host）
        try:
            host = public_endpoint.split(":")[0]
            if host and host not in ("localhost", "127.0.0.1"):
                self._internal_candidates.append((f"{host}:9000", False))
        except Exception:
            pass
        # 将 public_endpoint 作为最后的回退候选（用于宿主机直连反代域名的场景）
        self._internal_candidates.append((public_endpoint, public_secure))

        # 内部客户端：与 MinIO 实例通信（初始使用 _internal_endpoint，必要时在 make_bucket 中回退）
        self.client = Minio(
            self._internal_endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self._internal_secure,
        )
        # 公网（或反代主机名）客户端：仅用于生成预签名 URL（不会发起网络请求）
        self.public_client = Minio(
            public_endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=public_secure,
        )

        # 确保桶存在（容器内访问，包含内部端点回退逻辑）
        self.make_bucket()

    def make_bucket(self) -> str:
        """
        确保桶存在；若当前内部端点不可达，尝试多个常见候选端点进行回退。
        """
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
            return self.bucket_name
        except Exception as e:
            last_err = e
            # 端点回退尝试
            for ep, sec in getattr(self, "_internal_candidates", []):
                try:
                    self.client = Minio(
                        ep,
                        access_key=self.access_key,
                        secret_key=self.secret_key,
                        secure=sec,
                    )
                    if not self.client.bucket_exists(self.bucket_name):
                        self.client.make_bucket(self.bucket_name)
                    # 记录成功端点，便于后续 put/get/remove 复用
                    self._internal_endpoint = ep
                    self._internal_secure = sec
                    return self.bucket_name
                except Exception as e2:
                    last_err = e2
                    continue
            # 全部候选失败，抛出清晰错误
            raise RuntimeError(
                f"MinIO 内部端点不可达，已尝试 {getattr(self, '_internal_candidates', [])}: {repr(last_err)}"
            )

    def presigned_get_object(self, bucket_name, object_name):
        # Request URL expired after 7 days
        # 使用 public_client 生成对外可访问域名的预签名 URL（仅本地计算签名，无需连通性）
        url = self.public_client.presigned_get_object(
            bucket_name=bucket_name, object_name=object_name, expires=timedelta(days=7)
        )
        return url

    def check_file_name_exists(self, bucket_name, file_name):
        try:
            self.client.stat_object(bucket_name=bucket_name, object_name=file_name)
            return True
        except Exception:
            # 记录 stat 失败，但不暴露底层异常细节
            return False

    def stat_object(self, bucket_name, object_name):
        """
        获取对象的元信息（例如大小 size、content_type、etag 等）。
        便于上传后回填 size 到数据库记录。
        """
        return self.client.stat_object(bucket_name=bucket_name, object_name=object_name)

    def put_object(self, file_data, file_name, content_type):
        try:
            object_name = f"{uuid7()}{file_name}"
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=file_data,
                content_type=content_type,
                length=-1,
                part_size=10 * 1024 * 1024,
            )
            url = self.presigned_get_object(
                bucket_name=self.bucket_name, object_name=object_name
            )
            data_file = IMinioResponse(
                bucket_name=self.bucket_name, file_name=object_name, url=url
            )
            return data_file
        except Exception as e:
            raise e

    def get_object_bytes(self, bucket_name, object_name) -> bytes:
        """
        读取对象的原始字节数据（便于做重新索引或解析）。
        注意：需要确保关闭响应以释放连接。
        """
        response = self.client.get_object(bucket_name=bucket_name, object_name=object_name)
        try:
            data = response.read()
            return data
        finally:
            response.close()
            response.release_conn()

    def remove_object(self, bucket_name, object_name) -> None:
        """
        删除指定对象（用于清理已上传但不再需要的文件）。
        """
        self.client.remove_object(bucket_name=bucket_name, object_name=object_name)
