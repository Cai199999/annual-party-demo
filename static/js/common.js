/* =========================================================
   年会大屏系统 · 共用前端工具
   - 所有 HTTP 请求均为同源相对路径，不写死 IP
   - WebSocket 地址基于当前页面 host 动态生成
   ========================================================= */
(function () {
  "use strict";

  const App = {};

  /** 当前页面的 WebSocket 地址；https 下自动切换到 wss。 */
  App.wsUrl = function () {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${window.location.host}/ws`;
  };

  /**
   * fetch 封装：自动解析 JSON，并把后端 detail 转成可读错误。
   * path 传同源相对路径，例如 "/api/users"。
   */
  App.api = async function (path, options = {}) {
    const response = await fetch(path, options);
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      /* 非 JSON 响应 */
    }

    if (!response.ok) {
      let message = `请求失败（${response.status}）`;
      const detail = data && data.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((item) => item.msg || "参数错误").join("；");
      }
      const error = new Error(message);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  };

  /** 轻量 Toast，type: info | success | error | warn */
  App.toast = function (message, type = "info", duration = 2800) {
    let wrap = document.querySelector(".toast-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "toast-wrap";
      document.body.appendChild(wrap);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    wrap.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("show"));
    window.setTimeout(() => {
      toast.classList.remove("show");
      window.setTimeout(() => toast.remove(), 300);
    }, duration);
  };

  /**
   * 带自动重连的 WebSocket 连接。
   * handlers: { onMessage(data), onStatus("open"|"closed") }
   */
  App.connectWS = function (handlers = {}) {
    let socket = null;
    let closedByUser = false;
    let retries = 0;
    let retryTimer = null;

    const notifyStatus = (status) => {
      if (typeof handlers.onStatus === "function") {
        handlers.onStatus(status);
      }
    };

    const scheduleReconnect = () => {
      if (closedByUser) return;
      const delay = Math.min(1000 * Math.pow(1.8, retries), 8000);
      retries += 1;
      retryTimer = window.setTimeout(connect, delay);
    };

    const connect = () => {
      if (closedByUser) return;
      try {
        socket = new WebSocket(App.wsUrl());
      } catch (_) {
        scheduleReconnect();
        return;
      }

      socket.addEventListener("open", () => {
        retries = 0;
        notifyStatus("open");
      });

      socket.addEventListener("message", (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch (_) {
          return;
        }
        if (typeof handlers.onMessage === "function") {
          handlers.onMessage(data);
        }
      });

      socket.addEventListener("close", () => {
        notifyStatus("closed");
        if (!closedByUser) scheduleReconnect();
      });

      socket.addEventListener("error", () => {
        try {
          socket.close();
        } catch (_) {
          /* ignore */
        }
      });
    };

    connect();

    return {
      get isOpen() {
        return !!socket && socket.readyState === WebSocket.OPEN;
      },
      send(payload) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return false;
        socket.send(JSON.stringify(payload));
        return true;
      },
      close() {
        closedByUser = true;
        window.clearTimeout(retryTimer);
        if (socket) socket.close();
      },
    };
  };

  window.App = App;
})();
