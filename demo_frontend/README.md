# Three.js Demo Frontend

这个目录是给 `ktv_backend` 做最小联调验证的，不需要 Unity 就能先跑一遍：

- 连 WebSocket
- 发 `song_context`
- 发 `user_signal`
- 收 `agent_response`
- 收 `tts_chunk / tts_done`
- 用一个简化的 three.js 小人把动作和表情演出来

## 运行方式

1. 启动后端：

```powershell
python -m ktv_backend.server
```

2. 再开一个静态文件服务：

```powershell
python -m http.server 8080 --directory ktv_backend/demo_frontend
```

3. 浏览器打开：

```text
http://127.0.0.1:8080
```

## 最快验证路径

1. 点“连接”
2. 点“发送 song_context”
3. 在“用户文本”里输入一句话，比如 `小K我们一起唱副歌`
4. 点“发送 user_signal”
5. 观察：
   - 日志里有没有 `hello / ack / agent_response / tts_done`
   - 小人动作和表情有没有变化
   - 播放器有没有生成语音

## 说明

- three.js 是通过 CDN 加载的，所以浏览器需要联网。
- 音频文件上传目前建议先用 `wav`。
- 这个 demo 的目的不是做正式 UI，而是最快证明 `ktv_backend` 接口闭环已经通了。
