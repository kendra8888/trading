# Render 部署说明

1. 把这个文件夹上传到 GitHub 新仓库
2. 登录 Render
3. New -> Web Service
4. 连接 GitHub 仓库
5. Render 会读取 render.yaml 自动部署
6. 部署完成后会得到公网网址

本项目使用:
- buildCommand: pip install -r requirements.txt
- startCommand: gunicorn app:app
