# Bestdori 背景图批量下载器 (Bestdori BG Image Downloader) 🎸

Bestdori 场景背景图下载工具。

## 主要功能

这个工具用来批量下载 [Bestdori](https://bestdori.com) 资源库中的背景图（scenario）。

## 安装

```bash
# 克隆
git clone https://github.com/Yulinanami/Bestdori_BG_ImgDownload
cd Bestdori_BG_ImgDownload

# 创建虚拟环境
python -m venv .venv
# 或
python3 -m venv .venv

# 激活虚拟环境
.\.venv\Scripts\activate
# 或
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 使用

```bash
python main.py
```

## 注意

对于Linux版本需要在存放可执行文件的目录下使用命令启动

```bash
chmod +x Bestdori_BG_Linux_x64 
./Bestdori_BG_Linux_x64 
```

运行后按提示输入：

1) 起始/结束 scenario 编号（默认 0-123，可交换顺序）。  
2) 是否按 scenario 分目录保存（默认否，输入 Y/y 开启）。  
3) 输出目录。

或者直接一路回车即可。

## 📄 许可证

MIT License
