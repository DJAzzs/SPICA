# MusicFree 音乐服务部署（已完成 + 你还差的 3 步）

## 已部署（本机）

```sh
docker run -d --name music-free --restart unless-stopped \
  -p 14533:14533 \
  -v /home/dja/桌面/SPICA/musicfree-data:/app/data \
  -v /home/dja/桌面/SPICA/musicfree-music:/app/music \
  docker.1ms.run/ansgoo/music-free:latest
```

- 服务地址：http://127.0.0.1:14533 （OpenSubsonic ping 已验证 ✓）
- 数据目录：`SPICA/musicfree-data`（配置/库）+ `SPICA/musicfree-music`（音乐文件）
- 开机自启（docker restart 策略）
- SPICA 已自动连接（u/t/s 认证，账号配置在 run/settings.json）

## 你还差的 3 步（一次性，约 1 分钟）

远程搜索依赖音源插件，需在管理后台安装：

1. 浏览器打开 **http://127.0.0.1:14533**，用 **admin / admin** 登录（进去后改密码）
2. **插件商店 → 注册表订阅**，添加社区注册表：
   ```
   https://cdn.jsdelivr.net/npm/musicfree-plugin@latest/artifact/registry.json
   ```
3. 在商店里安装一个带 **RemoteSearch（远程搜索）** 能力的音源插件并启用（可多装几个不同平台源）

装完即刻生效（SPICA 无需重启）。然后对 SPICA 说：

> "Hey SPICA，放一首周杰伦的晴天"

## 日常使用

| 语音 / 命令 | 效果 |
|---|---|
| "放一首 XXX" / "来点音乐" | 搜索播放（随机挑一首） |
| "把音乐停了" | 停止 |
| `/music 播放 夜曲` · `/music next` · `/music stop` | 键盘控制 |
| 设置 → 任务自动配乐 | 每个任务开始时 flash 按任务气质自动选歌 |

播放时 SPICA 说话/你说话，音乐 1 秒内自动压低，说完 1 秒恢复（ducking）。
