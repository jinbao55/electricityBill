# 使用官方 Python 运行时作为父镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 将当前目录内容复制到容器的 /app 目录
COPY . /app

# 安装系统依赖（包括 MySQL 客户端开发包），并切换国内镜像源加速
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list && \
    sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y gcc default-libmysqlclient-dev pkg-config && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 暴露端口 5000（Flask 默认端口）
EXPOSE 5000

# 定义环境变量（可选）
ENV FLASK_APP=main.py
ENV FLASK_ENV=production

# 启动应用
CMD ["python", "main.py"]
