const {
  useState,
  useEffect,
  useRef
} = React;
const MAX_VIDEOS = 10;
function formatTimecode(sec) {
  if (sec === undefined || sec === null || isNaN(sec)) return "00:00.0";
  const totalTenths = Math.round(Math.max(0, Number(sec)) * 10);
  const mins = Math.floor(totalTenths / 600);
  const remTenths = totalTenths % 600;
  const secs = (remTenths / 10).toFixed(1);
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(4, '0')}`;
}
function splitDescriptionAndLaw(event) {
  const rule = event.rule || {};
  const workplace = rule.basis_type === "workplace_review_check";
  return {
    observation: event.description || "",
    law: [rule.section, rule.summary, rule.source_note].filter(Boolean).join(" — ") || "Источник не указан в результате.",
    label: workplace ? "КРИТЕРИЙ ПРОВЕРКИ РАБОЧЕГО МЕСТА" : "ОСНОВАНИЕ ПРОВЕРКИ",
    url: typeof rule.url === 'string' && /^https:\/\/adilet\.zan\.kz\//.test(rule.url) ? rule.url : null
  };
}
function ForteMark({
  className = "w-9 h-9"
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 64 64",
    fill: "none",
    className: className
  }, /*#__PURE__*/React.createElement("path", {
    d: "M10 34C10 20.745 20.745 10 34 10H54V20H34C26.268 20 20 26.268 20 34H10Z",
    fill: "currentColor"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M10 54C10 40.745 20.745 30 34 30H48V40H34C26.268 40 20 46.268 20 54H10Z",
    fill: "currentColor"
  }));
}
function App() {
  /**
   * Очередь до 10 видеозаписей:
   * каждый элемент: {
   *   id: string,
   *   file: File,
   *   name: string,
   *   sizeMB: string,
   *   videoUrl: string,
   *   status: 'idle' | 'uploading' | 'processing' | 'done' | 'failed',
   *   jobId: string | null,
   *   elapsedSec: number,
   *   result: object | null,
   *   errorMsg: string | null
   * }
   */
  const [queue, setQueue] = useState([]);
  const [apiKey, setApiKey] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const runLock = useRef(false);
  const alive = useRef(true);
  const [activeId, setActiveId] = useState(null);
  const [limitNotice, setLimitNotice] = useState(null);

  // Состояния видеоплеера для текущего выбранного видео
  const [videoDuration, setVideoDuration] = useState(30);
  const [currentTime, setCurrentTime] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [activeViolationIdx, setActiveViolationIdx] = useState(0);
  const [lightboxFrame, setLightboxFrame] = useState(null);
  const videoRef = useRef(null);
  const fileInputRef = useRef(null);
  const pollTimersRef = useRef({});
  const clockTimersRef = useRef({});
  useEffect(() => {
    return () => {
      alive.current = false;
      Object.values(pollTimersRef.current).forEach(clearInterval);
      Object.values(clockTimersRef.current).forEach(clearInterval);
    };
  }, []);
  useEffect(() => {
    if (!lightboxFrame) return;
    const onKeyDown = e => {
      if (e.key === "Escape") setLightboxFrame(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lightboxFrame]);
  const activeItem = queue.find(item => item.id === activeId) || queue[0] || null;

  // При переключении между видео в левом списке сбрасываем индекс нарушения и применяем скорость
  useEffect(() => {
    setActiveViolationIdx(0);
    setCurrentTime(0);
    if (videoRef.current) {
      videoRef.current.playbackRate = playbackSpeed;
    }
  }, [activeItem?.id]);
  const updateQueueItem = (id, patch) => {
    setQueue(prev => prev.map(item => item.id === id ? {
      ...item,
      ...(typeof patch === "function" ? patch(item) : patch)
    } : item));
  };
  const handleFilesAdded = fileList => {
    if (!fileList || fileList.length === 0) return;
    const incoming = Array.from(fileList).filter(file => /\.(mov|mp4|m4v)$/i.test(file.name) && file.size <= 95 * 1024 * 1024);
    if (incoming.length !== fileList.length) {
      setLimitNotice("Форматы MOV / MP4 / M4V, до 95 МБ на файл для публичного HTTPS.");
      return;
    }
    setQueue(prev => {
      const availableSlots = MAX_VIDEOS - prev.length;
      if (availableSlots <= 0) {
        setLimitNotice(`Достигнут максимум: ${MAX_VIDEOS} видео за один сеанс.`);
        setTimeout(() => setLimitNotice(null), 4000);
        return prev;
      }
      if (incoming.length > availableSlots) {
        setLimitNotice(`Добавлено ${availableSlots} из ${incoming.length} файлов (максимум ${MAX_VIDEOS} видео).`);
        setTimeout(() => setLimitNotice(null), 4000);
      } else {
        setLimitNotice(null);
      }
      const toAdd = incoming.slice(0, availableSlots).map((file, idx) => ({
        id: `${Date.now()}_${idx}_${Math.random().toString(36).slice(2, 6)}`,
        file,
        name: file.name,
        sizeMB: (file.size / (1024 * 1024)).toFixed(2),
        videoUrl: URL.createObjectURL(file),
        status: "idle",
        jobId: null,
        elapsedSec: 0,
        result: null,
        errorMsg: null
      }));
      const nextQueue = [...prev, ...toAdd];
      if (toAdd.length > 0 && (!activeId || prev.length === 0)) {
        setActiveId(toAdd[0].id);
      }
      return nextQueue;
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };
  const handleDrop = e => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFilesAdded(e.dataTransfer.files);
    }
  };
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const runItem = async (item, key) => {
    updateQueueItem(item.id, {
      status: "uploading",
      errorMsg: null,
      result: null,
      elapsedSec: 0
    });
    const started = Date.now();
    clockTimersRef.current[item.id] = setInterval(() => updateQueueItem(item.id, {
      elapsedSec: Math.floor((Date.now() - started) / 1000)
    }), 1000);
    try {
      let response;
      for (let attempt = 0; attempt < 40; attempt++) {
        const form = new FormData();
        form.append("file", item.file);
        response = await fetch("/api/v1/analyze", {
          method: "POST",
          headers: {
            "X-API-Key": key
          },
          body: form
        });
        if (response.status !== 429) break;
        updateQueueItem(item.id, {
          status: "processing",
          stage: "Ожидание свободного GPU"
        });
        await delay(15000);
        if (!alive.current) return;
      }
      if (!response.ok) {
        const problem = await response.json().catch(() => ({}));
        throw new Error(problem.detail || `Ошибка HTTP ${response.status}`);
      }
      const job = await response.json();
      updateQueueItem(item.id, {
        status: "processing",
        jobId: job.job_id
      });
      const deadline = Date.now() + 330000;
      let networkErrors = 0;
      while (alive.current && Date.now() < deadline) {
        await delay(1200);
        let res;
        try {
          res = await fetch(`/api/v1/jobs/${job.job_id}`, {
            headers: {
              "X-API-Key": key
            }
          });
          networkErrors = 0;
        } catch (error) {
          if (++networkErrors <= 3) continue;
          throw error;
        }
        if (!res.ok) throw new Error(`Ошибка получения результата: HTTP ${res.status}`);
        const data = await res.json();
        if (data.status === "done") {
          updateQueueItem(item.id, {
            status: "done",
            result: data
          });
          return;
        }
        if (data.status === "failed") throw new Error(data.error || "Анализ не выполнен; результат не получен");
        updateQueueItem(item.id, {
          stage: data.stage,
          progress: data.progress
        });
      }
      if (alive.current) throw new Error("Время ожидания истекло. Сохраните JOB_ID для проверки результата.");
    } catch (error) {
      updateQueueItem(item.id, {
        status: "failed",
        errorMsg: error.message
      });
    } finally {
      clearInterval(clockTimersRef.current[item.id]);
    }
  };
  const runItems = async items => {
    if (runLock.current) {
      setLimitNotice("Дождитесь завершения текущей очереди.");
      return;
    }
    if (!apiKey.trim()) {
      setLimitNotice("Введите API-ключ перед запуском анализа.");
      return;
    }
    runLock.current = true;
    setIsRunning(true);
    setLimitNotice(null);
    try {
      for (const item of items) {
        if (!alive.current) break;
        await runItem(item, apiKey.trim());
      }
    } finally {
      runLock.current = false;
      setIsRunning(false);
    }
  };
  const analyzeSingleItem = item => item && runItems([item]);
  const handleAnalyzeAllPending = () => runItems(queue.filter(it => it.status === "idle" || it.status === "failed"));
  const removeQueueItem = (e, id) => {
    e.stopPropagation();
    if (runLock.current) return;
    clearInterval(pollTimersRef.current[id]);
    clearInterval(clockTimersRef.current[id]);
    setQueue(prev => {
      const target = prev.find(item => item.id === id);
      if (target?.videoUrl) {
        URL.revokeObjectURL(target.videoUrl);
      }
      const next = prev.filter(item => item.id !== id);
      if (activeId === id) {
        setActiveId(next[0]?.id || null);
      }
      return next;
    });
  };
  const clearAllQueue = () => {
    if (runLock.current) return;
    Object.values(pollTimersRef.current).forEach(clearInterval);
    Object.values(clockTimersRef.current).forEach(clearInterval);
    queue.forEach(item => {
      if (item?.videoUrl) URL.revokeObjectURL(item.videoUrl);
    });
    setQueue([]);
    setActiveId(null);
    setLimitNotice(null);
    setPlaybackSpeed(1.0);
  };
  const seekToSeconds = (sec, violationIndex = null) => {
    if (violationIndex !== null) {
      setActiveViolationIdx(violationIndex);
    }
    if (videoRef.current) {
      const clamped = Math.max(0, Math.min(sec, videoDuration || 9999));
      videoRef.current.currentTime = clamped;
      videoRef.current.pause();
      setCurrentTime(clamped);
    }
  };
  const changeSpeed = rate => {
    setPlaybackSpeed(rate);
    if (videoRef.current) {
      videoRef.current.playbackRate = rate;
    }
  };
  const getFrameSrc = base64Str => {
    if (!base64Str) return "";
    return base64Str.startsWith("data:") ? base64Str : `data:image/jpeg;base64,${base64Str}`;
  };

  // Статистика по очереди из до 10 видео
  const doneCount = queue.filter(i => i.status === "done").length;
  const busyCount = queue.filter(i => i.status === "uploading" || i.status === "processing").length;
  const idleCount = queue.filter(i => i.status === "idle" || i.status === "failed").length;

  // Генерация спектра событий для активного видео
  const activeResult = activeItem?.result || null;
  const waveformBars = Array.from({
    length: 48
  }, (_, i) => {
    const barTime = (i + 0.5) / 48 * (videoDuration || 30);
    const nearViolation = (activeResult?.violations || []).some(v => Math.abs(v.timecode_sec - barTime) <= Math.max(0.8, (videoDuration || 30) * 0.03));
    const heightPct = nearViolation ? 95 : 12;
    return {
      heightPct,
      nearViolation,
      barTime
    };
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "min-h-screen flex flex-col lg:flex-row"
  }, /*#__PURE__*/React.createElement("input", {
    ref: fileInputRef,
    type: "file",
    multiple: true,
    accept: ".mov,.mp4,.m4v",
    className: "hidden",
    onChange: e => handleFilesAdded(e.target.files)
  }), /*#__PURE__*/React.createElement("aside", {
    className: "w-full lg:w-80 xl:w-[340px] bg-obsidian text-white flex flex-col justify-between p-5 lg:p-6 shrink-0 lg:min-h-screen lg:sticky lg:top-0 lg:h-screen border-b lg:border-b-0 lg:border-r border-white/10"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex flex-col min-h-0 flex-1"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex items-center justify-between pb-4 border-b border-white/10 shrink-0"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex items-center space-x-3"
  }, /*#__PURE__*/React.createElement("div", {
    className: "w-10 h-10 rounded-2xl bg-forte flex items-center justify-center text-white shadow-lg shadow-forte/40"
  }, /*#__PURE__*/React.createElement(ForteMark, {
    className: "w-6 h-6"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "font-display font-bold text-base tracking-tight text-white"
  }, "GASH", /*#__PURE__*/React.createElement("span", {
    className: "text-forte-vivid"
  }, "."), "Контроль"), /*#__PURE__*/React.createElement("div", {
    className: "font-mono text-[10px] uppercase tracking-widest text-neutral-400"
  }, "Видеоинспекция кассы"))), /*#__PURE__*/React.createElement("div", {
    className: "px-2.5 py-1 rounded-lg bg-white/[0.06] border border-white/10 font-mono text-xs font-bold"
  }, /*#__PURE__*/React.createElement("span", {
    className: queue.length >= MAX_VIDEOS ? "text-forte-vivid" : "text-white"
  }, queue.length), /*#__PURE__*/React.createElement("span", {
    className: "text-neutral-500"
  }, "/", MAX_VIDEOS))), /*#__PURE__*/React.createElement("label", {
    className: "block mt-4 text-xs text-neutral-300"
  }, "API-ключ", /*#__PURE__*/React.createElement("input", {
    type: "password",
    autoComplete: "off",
    value: apiKey,
    disabled: isRunning,
    onChange: event => setApiKey(event.target.value),
    placeholder: "Введите ключ доступа",
    className: "mt-2 w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-white"
  }), /*#__PURE__*/React.createElement("span", {
    className: "block mt-1 text-[10px] text-neutral-400"
  }, "Ключ хранится только в памяти этой вкладки.")), /*#__PURE__*/React.createElement("div", {
    className: "mt-4 space-y-2 shrink-0"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex gap-2"
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => fileInputRef.current?.click(),
    disabled: queue.length >= MAX_VIDEOS,
    className: `flex-1 px-3.5 py-2.5 rounded-xl border text-left transition flex items-center justify-between ${queue.length >= MAX_VIDEOS ? "bg-white/[0.03] border-white/5 text-neutral-500 cursor-not-allowed" : "bg-white/[0.07] hover:bg-white/[0.12] border-white/10 text-white cursor-pointer"}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "text-xs font-bold"
  }, "+ Добавить видео (до 10)"), /*#__PURE__*/React.createElement("span", {
    className: "font-mono text-xs text-forte-vivid font-bold"
  }, "↑")), queue.length > 0 && /*#__PURE__*/React.createElement("button", {
    onClick: clearAllQueue,
    title: "Очистить весь список",
    className: "px-3 py-2.5 rounded-xl bg-white/[0.05] hover:bg-rose-950/80 border border-white/10 hover:border-forte text-neutral-400 hover:text-white text-xs font-mono transition cursor-pointer"
  }, "Очистить")), idleCount > 0 && /*#__PURE__*/React.createElement("button", {
    onClick: handleAnalyzeAllPending,
    disabled: isRunning || !apiKey.trim(),
    className: "w-full px-4 py-3 rounded-xl bg-forte hover:bg-forte-vivid text-white font-display text-xs font-bold uppercase tracking-wider shadow-lg shadow-forte/30 transition cursor-pointer flex items-center justify-between"
  }, /*#__PURE__*/React.createElement("span", null, idleCount === 1 ? "Запустить анализ (1)" : `Проверить все видео (${idleCount})`), /*#__PURE__*/React.createElement("span", null, "→")), limitNotice && /*#__PURE__*/React.createElement("div", {
    className: "p-2.5 rounded-xl bg-forte/20 border border-forte-vivid/40 text-[11px] text-rose-200 font-medium"
  }, limitNotice)), /*#__PURE__*/React.createElement("div", {
    className: "mt-5 pt-4 border-t border-white/10 flex-1 flex flex-col min-h-0"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex items-center justify-between font-mono text-[10px] uppercase tracking-widest text-neutral-400 mb-2.5 shrink-0"
  }, /*#__PURE__*/React.createElement("span", null, "ОЧЕРЕДЬ ПРОВЕРКИ ВИДЕО"), /*#__PURE__*/React.createElement("span", null, "Готово: ", /*#__PURE__*/React.createElement("strong", {
    className: "text-white"
  }, doneCount, "/", queue.length))), queue.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "h-1.5 w-full bg-white/10 rounded-full overflow-hidden mb-3 shrink-0"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h-full bg-gradient-to-r from-forte to-emerald-400 transition-all duration-300",
    style: {
      width: `${Math.round(doneCount / Math.max(queue.length, 1) * 100)}%`
    }
  })), queue.length === 0 ? /*#__PURE__*/React.createElement("div", {
    onClick: () => fileInputRef.current?.click(),
    className: "flex-1 rounded-2xl border border-dashed border-white/10 hover:border-forte/60 bg-white/[0.02] hover:bg-white/[0.04] transition p-5 flex flex-col items-center justify-center text-center cursor-pointer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center text-neutral-400 mb-2 font-mono text-sm"
  }, "0/10"), /*#__PURE__*/React.createElement("div", {
    className: "text-xs font-bold text-neutral-300"
  }, "Список видео пуст"), /*#__PURE__*/React.createElement("p", {
    className: "text-[11px] text-neutral-500 mt-1 leading-relaxed"
  }, "Загрузите от 1 до 10 файлов ", /*#__PURE__*/React.createElement("code", {
    className: "text-neutral-300"
  }, ".mov"), ", чтобы отслеживать их прогресс и переключаться между результатами")) : /*#__PURE__*/React.createElement("div", {
    className: "flex-1 overflow-y-auto space-y-2 pr-1"
  }, queue.map((item, idx) => {
    const isSelected = activeItem?.id === item.id;
    const violationsCount = item.result?.violations?.length || 0;
    return /*#__PURE__*/React.createElement("div", {
      key: item.id,
      onClick: () => setActiveId(item.id),
      className: `group relative rounded-2xl p-3 transition-all cursor-pointer border ${isSelected ? "bg-white/[0.12] border-forte-vivid shadow-md" : "bg-white/[0.03] hover:bg-white/[0.07] border-white/5"}`
    }, /*#__PURE__*/React.createElement("div", {
      className: "flex items-start justify-between gap-2"
    }, /*#__PURE__*/React.createElement("div", {
      className: "flex items-center space-x-2.5 min-w-0"
    }, /*#__PURE__*/React.createElement("span", {
      className: `w-6 h-6 rounded-lg font-mono text-[11px] font-bold flex items-center justify-center shrink-0 ${isSelected ? "bg-forte text-white" : "bg-white/10 text-neutral-400"}`
    }, String(idx + 1).padStart(2, "0")), /*#__PURE__*/React.createElement("div", {
      className: "min-w-0"
    }, /*#__PURE__*/React.createElement("div", {
      className: "text-xs font-bold text-white truncate"
    }, item.name), /*#__PURE__*/React.createElement("div", {
      className: "font-mono text-[10px] text-neutral-400"
    }, item.sizeMB, " МБ"))), /*#__PURE__*/React.createElement("button", {
      onClick: e => removeQueueItem(e, item.id),
      title: "Убрать из списка",
      className: "w-5 h-5 rounded-full hover:bg-white/20 text-neutral-500 hover:text-white flex items-center justify-center text-[10px] shrink-0 transition"
    }, "✕")), /*#__PURE__*/React.createElement("div", {
      className: "mt-2.5 pt-2 border-t border-white/5 flex items-center justify-between text-[11px]"
    }, item.status === "idle" && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
      className: "font-mono text-neutral-400"
    }, "Ожидает запуска"), /*#__PURE__*/React.createElement("button", {
      onClick: e => {
        e.stopPropagation();
        setActiveId(item.id);
        analyzeSingleItem(item);
      },
      className: "px-2 py-0.5 rounded bg-forte/80 hover:bg-forte text-white font-mono text-[10px] font-bold transition"
    }, "▶ Проверить")), (item.status === "uploading" || item.status === "processing") && /*#__PURE__*/React.createElement("div", {
      className: "w-full flex items-center justify-between font-mono text-amber-300"
    }, /*#__PURE__*/React.createElement("span", {
      className: "flex items-center space-x-1.5"
    }, /*#__PURE__*/React.createElement("span", {
      className: "w-2 h-2 rounded-full bg-amber-400 animate-ping"
    }), /*#__PURE__*/React.createElement("span", null, item.status === "uploading" ? "Загрузка..." : "Анализ...")), /*#__PURE__*/React.createElement("span", null, item.elapsedSec, " сек")), item.status === "done" && item.result && /*#__PURE__*/React.createElement("div", {
      className: "w-full flex items-center justify-between"
    }, item.result.verdict === "violation" ? /*#__PURE__*/React.createElement("span", {
      className: "px-2 py-0.5 rounded-md bg-forte-vivid/25 border border-forte-vivid/50 text-rose-200 font-mono text-[10px] font-bold"
    }, "! Нарушений: ", violationsCount) : /*#__PURE__*/React.createElement("span", {
      className: "px-2 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-bold"
    }, "✓ Нарушений нет"), /*#__PURE__*/React.createElement("span", {
      className: "font-mono text-[10px] text-neutral-400 group-hover:text-white"
    }, "Открыть →")), item.status === "failed" && /*#__PURE__*/React.createElement("div", {
      className: "w-full flex items-center justify-between text-rose-400 font-mono text-[10px]"
    }, /*#__PURE__*/React.createElement("span", null, "✕ Ошибка"), /*#__PURE__*/React.createElement("button", {
      onClick: e => {
        e.stopPropagation();
        analyzeSingleItem(item);
      },
      className: "underline hover:text-white"
    }, "Повторить"))));
  })))), /*#__PURE__*/React.createElement("div", {
    className: "pt-4 border-t border-white/10 mt-4 space-y-2.5 shrink-0"
  }, /*#__PURE__*/React.createElement("p", {
    className: "text-[11px] text-neutral-400 leading-relaxed"
  }, "До 10 видео обрабатываются последовательно. Основание каждой проверки указано в результате. Требуется проверка человеком."), /*#__PURE__*/React.createElement("div", {
    className: "flex items-center justify-between font-mono text-[10px] text-neutral-500"
  }, /*#__PURE__*/React.createElement("span", {
    className: "flex items-center space-x-1.5 text-emerald-400"
  }, /*#__PURE__*/React.createElement("span", {
    className: "w-1.5 h-1.5 rounded-full bg-emerald-400"
  }), /*#__PURE__*/React.createElement("span", null, "GPU AI")), /*#__PURE__*/React.createElement("span", null, "До 10 видео за сеанс")))), /*#__PURE__*/React.createElement("main", {
    className: "flex-1 min-w-0 p-5 sm:p-8 lg:p-10 flex flex-col justify-between"
  }, /*#__PURE__*/React.createElement("div", {
    className: "max-w-6xl w-full mx-auto space-y-8"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-6 border-b editorial-border"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "font-mono text-xs uppercase tracking-widest text-forte font-bold mb-1"
  }, "// СИСТЕМА ВИДЕОАНАЛИТИКИ КАССОВЫХ ОПЕРАЦИЙ"), /*#__PURE__*/React.createElement("h1", {
    className: "font-display text-2xl sm:text-3xl font-bold tracking-tight text-obsidian"
  }, "Инспекция кассовой дисциплины")), activeItem && /*#__PURE__*/React.createElement("div", {
    className: "flex items-center space-x-2 font-mono text-xs bg-card px-4 py-2 rounded-full border editorial-border"
  }, /*#__PURE__*/React.createElement("span", {
    className: "text-neutral-500"
  }, "Активный файл:"), /*#__PURE__*/React.createElement("strong", {
    className: "text-obsidian truncate max-w-[220px]"
  }, activeItem.name))), (!activeItem || activeItem.status === "idle") && /*#__PURE__*/React.createElement("div", {
    className: "bg-card rounded-[28px] border editorial-border p-7 sm:p-10 flex flex-col justify-between shadow-sm"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "flex items-center justify-between mb-6"
  }, /*#__PURE__*/React.createElement("span", {
    className: "font-display text-xs uppercase tracking-wider px-3.5 py-1.5 rounded-full bg-forte/10 text-forte font-bold"
  }, "Пакетная загрузка до 10 видео"), /*#__PURE__*/React.createElement("span", {
    className: "font-mono text-xs text-neutral-500"
  }, "Загружено в очередь: ", queue.length, " / ", MAX_VIDEOS)), /*#__PURE__*/React.createElement("div", {
    onDragOver: e => e.preventDefault(),
    onDrop: handleDrop,
    onClick: () => fileInputRef.current?.click(),
    className: `group rounded-3xl border-2 border-dashed transition-all duration-300 p-8 sm:p-12 cursor-pointer ${activeItem ? "border-forte bg-forte-tint/60" : "border-neutral-300 hover:border-forte bg-paper/60 hover:bg-forte-tint/30"}`
  }, !activeItem ? /*#__PURE__*/React.createElement("div", {
    className: "max-w-xl mx-auto text-center space-y-4 py-4"
  }, /*#__PURE__*/React.createElement("div", {
    className: "w-16 h-16 rounded-2xl bg-obsidian text-white mx-auto flex items-center justify-center group-hover:bg-forte transition"
  }, /*#__PURE__*/React.createElement("svg", {
    className: "w-7 h-7",
    fill: "none",
    stroke: "currentColor",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    strokeLinecap: "round",
    strokeLinejoin: "round",
    strokeWidth: "1.8",
    d: "M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "font-display text-lg sm:text-xl font-bold text-obsidian"
  }, "Перетащите от 1 до 10 видеозаписей ", /*#__PURE__*/React.createElement("span", {
    className: "text-forte"
  }, ".mov"), " сюда"), /*#__PURE__*/React.createElement("p", {
    className: "text-sm text-neutral-600 mt-1.5 leading-relaxed"
  }, "Или нажмите для выбора нескольких файлов сразу. В левой панели вы сможете отслеживать прогресс каждого видео и мгновенно переключаться между их результатами."))) : /*#__PURE__*/React.createElement("div", {
    className: "max-w-2xl mx-auto space-y-4",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "bg-obsidian rounded-2xl overflow-hidden h-[380px] sm:h-[440px] flex items-center justify-center relative shadow-lg"
  }, /*#__PURE__*/React.createElement("video", {
    src: activeItem.videoUrl,
    controls: true,
    className: "w-full h-full object-contain",
    onLoadedMetadata: e => setVideoDuration(e.target.duration || 30)
  }), /*#__PURE__*/React.createElement("div", {
    className: "absolute top-3 left-3 px-3 py-1 rounded-full bg-black/75 backdrop-blur text-white font-mono text-xs pointer-events-none"
  }, activeItem.name)), /*#__PURE__*/React.createElement("div", {
    className: "flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-600 pt-1"
  }, /*#__PURE__*/React.createElement("span", {
    className: "font-mono font-semibold text-obsidian"
  }, "Размер: ", activeItem.sizeMB, " МБ • В очереди всего: ", queue.length, " видео"), queue.length < MAX_VIDEOS && /*#__PURE__*/React.createElement("button", {
    onClick: () => fileInputRef.current?.click(),
    className: "underline text-forte font-bold cursor-pointer"
  }, "+ Добавить ещё видео в очередь"))))), /*#__PURE__*/React.createElement("div", {
    className: "mt-7 pt-6 border-t editorial-border flex flex-col sm:flex-row sm:items-center justify-between gap-4"
  }, /*#__PURE__*/React.createElement("div", {
    className: "text-xs text-neutral-500"
  }, "Вы можете запустить проверку только текущего ролика или сразу всей очереди слева."), /*#__PURE__*/React.createElement("div", {
    className: "flex flex-wrap items-center gap-3 shrink-0"
  }, idleCount > 1 && /*#__PURE__*/React.createElement("button", {
    onClick: handleAnalyzeAllPending,
    disabled: isRunning || !apiKey.trim(),
    className: "px-6 py-4 rounded-full bg-obsidian hover:bg-neutral-800 text-white font-display text-xs font-bold uppercase tracking-wider transition cursor-pointer"
  }, "Проверить все (", idleCount, ")"), /*#__PURE__*/React.createElement("button", {
    disabled: !activeItem,
    onClick: () => activeItem && analyzeSingleItem(activeItem),
    className: `px-8 py-4 rounded-full font-display text-xs font-bold uppercase tracking-wider transition flex items-center justify-center space-x-3 ${activeItem ? "bg-forte hover:bg-forte-deep text-white shadow-lg shadow-forte/25 cursor-pointer" : "bg-neutral-300 text-neutral-500 cursor-not-allowed"}`
  }, /*#__PURE__*/React.createElement("span", null, "Запустить анализ видео"), /*#__PURE__*/React.createElement("span", null, "→"))))), activeItem && (activeItem.status === "uploading" || activeItem.status === "processing") && /*#__PURE__*/React.createElement("div", {
    className: "bg-card rounded-[28px] border editorial-border p-10 sm:p-14 text-center max-w-2xl mx-auto my-8 space-y-6"
  }, /*#__PURE__*/React.createElement("div", {
    className: "w-16 h-16 rounded-2xl bg-forte text-white mx-auto flex items-center justify-center shadow-lg shadow-forte/30 animate-pulse"
  }, /*#__PURE__*/React.createElement(ForteMark, {
    className: "w-9 h-9"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "font-mono text-xs font-bold uppercase tracking-widest text-forte mb-2"
  }, "СТАТУС: ", activeItem.status === "uploading" ? "UPLOADING" : "PROCESSING", " • ", activeItem.elapsedSec, " СЕК"), /*#__PURE__*/React.createElement("h2", {
    className: "font-display text-xl sm:text-2xl font-bold text-obsidian"
  }, "Анализ файла: ", activeItem.name), /*#__PURE__*/React.createElement("p", {
    className: "font-mono text-xs text-neutral-500 mt-2"
  }, "JOB_ID: ", activeItem.jobId || "регистрация..."), queue.length > 1 && /*#__PURE__*/React.createElement("p", {
    className: "text-xs text-neutral-500 mt-4"
  }, "Вы можете переключаться на уже проверенные видео в списке слева, пока этот ролик обрабатывается."))), activeItem && activeItem.status === "failed" && /*#__PURE__*/React.createElement("div", {
    className: "bg-card rounded-[28px] border-2 border-forte p-8 text-center max-w-xl mx-auto space-y-4"
  }, /*#__PURE__*/React.createElement("div", {
    className: "font-mono text-xs font-bold uppercase text-forte"
  }, "СТАТУС: FAILED"), /*#__PURE__*/React.createElement("h3", {
    className: "font-display text-lg font-bold text-obsidian"
  }, activeItem.errorMsg), /*#__PURE__*/React.createElement("button", {
    onClick: () => analyzeSingleItem(activeItem),
    className: "px-6 py-3 rounded-full bg-obsidian text-white font-display text-xs font-bold cursor-pointer"
  }, "Повторить анализ файла")), activeItem && activeItem.status === "done" && activeResult && /*#__PURE__*/React.createElement("div", {
    className: "space-y-8"
  }, /*#__PURE__*/React.createElement("div", {
    className: `rounded-[28px] p-6 sm:p-8 border flex flex-col md:flex-row md:items-center justify-between gap-6 ${activeResult.verdict === "violation" ? "bg-forte text-white border-forte" : "bg-emerald-900 text-white border-emerald-800"}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "space-y-2"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex flex-wrap items-center gap-2.5 font-mono text-xs"
  }, /*#__PURE__*/React.createElement("span", {
    className: "px-3 py-1 rounded-full bg-black/25 font-bold uppercase"
  }, "VERDICT: ", activeResult.verdict), /*#__PURE__*/React.createElement("span", {
    className: "px-3 py-1 rounded-full bg-white/15"
  }, "JOB_ID: ", activeResult.job_id), /*#__PURE__*/React.createElement("span", {
    className: "px-3 py-1 rounded-full bg-white/15"
  }, "ФАЙЛ: ", activeItem.name)), /*#__PURE__*/React.createElement("h2", {
    className: "font-display text-xl sm:text-3xl font-bold tracking-tight"
  }, activeResult.verdict === "violation" ? "Обнаружены признаки возможных нарушений" : "Нарушение не обнаружено")), /*#__PURE__*/React.createElement("div", {
    className: "font-display text-right shrink-0"
  }, /*#__PURE__*/React.createElement("div", {
    className: "text-3xl sm:text-4xl font-extrabold"
  }, String(activeResult.violations?.length || 0).padStart(2, '0')), /*#__PURE__*/React.createElement("div", {
    className: "font-mono text-[10px] uppercase tracking-widest text-white/75"
  }, "Зафиксировано событий"))), /*#__PURE__*/React.createElement("div", {
    className: "grid grid-cols-1 lg:grid-cols-12 gap-8 items-start"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg:col-span-5 space-y-4 lg:sticky lg:top-8"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bg-obsidian text-white rounded-[28px] overflow-hidden shadow-xl border border-black"
  }, /*#__PURE__*/React.createElement("div", {
    className: "px-5 py-3.5 flex items-center justify-between border-b border-white/10 font-mono text-xs"
  }, /*#__PURE__*/React.createElement("span", {
    className: "truncate text-neutral-300"
  }, activeItem.name), /*#__PURE__*/React.createElement("span", {
    className: "text-forte-vivid font-bold shrink-0 ml-2"
  }, formatTimecode(currentTime))), /*#__PURE__*/React.createElement("div", {
    className: "bg-black h-[380px] sm:h-[440px] flex items-center justify-center"
  }, activeItem.videoUrl ? /*#__PURE__*/React.createElement("video", {
    key: activeItem.id,
    ref: videoRef,
    src: activeItem.videoUrl,
    controls: true,
    onLoadedMetadata: e => {
      setVideoDuration(e.target.duration || 30);
      e.target.playbackRate = playbackSpeed;
    },
    onTimeUpdate: e => setCurrentTime(e.target.currentTime),
    className: "w-full h-full object-contain"
  }) : /*#__PURE__*/React.createElement("div", {
    className: "text-neutral-500 text-xs"
  }, "Видеопоток недоступен")), /*#__PURE__*/React.createElement("div", {
    className: "px-5 py-3 bg-white/[0.03] border-t border-white/10 flex items-center justify-between"
  }, /*#__PURE__*/React.createElement("span", {
    className: "font-mono text-[11px] uppercase tracking-wider text-neutral-400"
  }, "Скорость воспроизведения"), /*#__PURE__*/React.createElement("div", {
    className: "flex items-center space-x-1.5 font-mono"
  }, [0.25, 0.5, 1.0, 1.5].map(rate => /*#__PURE__*/React.createElement("button", {
    key: rate,
    onClick: () => changeSpeed(rate),
    className: `px-2.5 py-1 rounded-full text-xs font-bold transition cursor-pointer ${playbackSpeed === rate ? "bg-forte text-white" : "bg-white/10 text-neutral-300 hover:bg-white/20"}`
  }, rate, "x")))), /*#__PURE__*/React.createElement("div", {
    className: "p-5 border-t border-white/10"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-neutral-400 mb-2.5"
  }, /*#__PURE__*/React.createElement("span", null, "Спектр событий видеозаписи"), /*#__PURE__*/React.createElement("span", null, "Нажмите на пик для перехода")), /*#__PURE__*/React.createElement("div", {
    onClick: e => {
      const rect = e.currentTarget.getBoundingClientRect();
      const ratio = (e.clientX - rect.left) / rect.width;
      seekToSeconds(ratio * (videoDuration || 30));
    },
    className: "relative h-12 bg-white/[0.04] rounded-2xl px-2 flex items-end justify-between gap-[2px] py-2 cursor-pointer overflow-hidden"
  }, /*#__PURE__*/React.createElement("div", {
    className: "absolute top-0 bottom-0 left-0 bg-white/10 border-r-2 border-white pointer-events-none z-10",
    style: {
      width: `${Math.min(100, currentTime / Math.max(videoDuration, 1) * 100)}%`
    }
  }), waveformBars.map((bar, bIdx) => /*#__PURE__*/React.createElement("div", {
    key: bIdx,
    style: {
      height: `${bar.heightPct}%`
    },
    className: `flex-1 rounded-full transition-all ${bar.nearViolation ? "bg-forte-vivid shadow-[0_0_8px_#C81E58]" : "bg-white/20"}`
  }))), (activeResult.violations || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "flex flex-wrap gap-2 mt-3"
  }, activeResult.violations.map((v, idx) => /*#__PURE__*/React.createElement("button", {
    key: idx,
    onClick: () => seekToSeconds(v.timecode_sec, idx),
    className: "px-3 py-1 rounded-full bg-forte hover:bg-forte-vivid text-white font-mono text-xs font-bold transition cursor-pointer"
  }, "▶ Эпизод #", idx + 1, " • ", v.timecode_sec, " сек")))))), /*#__PURE__*/React.createElement("div", {
    className: "lg:col-span-7"
  }, activeResult.verdict === "no_violation" || !activeResult.violations?.length ? /*#__PURE__*/React.createElement("div", {
    className: "bg-card rounded-[28px] border editorial-border p-10 text-center space-y-3"
  }, /*#__PURE__*/React.createElement("div", {
    className: "font-display text-xl font-bold text-obsidian"
  }, "Нарушение не обнаружено"), /*#__PURE__*/React.createElement("p", {
    className: "text-sm text-neutral-600 max-w-md mx-auto"
  }, "Модель не обнаружила подтверждённых признаков по включённым проверкам. Это не гарантирует отсутствие нарушений; проверьте запись вручную.")) : /*#__PURE__*/React.createElement("div", {
    className: "relative pl-6 sm:pl-10 border-l-2 border-forte/30 space-y-8"
  }, activeResult.violations.map((v, idx) => {
    const {
      observation,
      law,
      label,
      url
    } = splitDescriptionAndLaw(v);
    const isSelected = activeViolationIdx === idx;
    return /*#__PURE__*/React.createElement("article", {
      key: idx,
      onClick: () => setActiveViolationIdx(idx),
      className: `relative bg-card rounded-[28px] p-6 sm:p-8 transition-all border ${isSelected ? "border-2 border-forte shadow-xl" : "editorial-border hover:border-neutral-400"}`
    }, /*#__PURE__*/React.createElement("div", {
      className: `-left-[35px] sm:-left-[51px] top-7 w-6 h-6 rounded-full border-4 border-paper flex items-center justify-center transition ${isSelected ? "bg-forte scale-125" : "bg-obsidian"} absolute`
    }), /*#__PURE__*/React.createElement("div", {
      className: "flex flex-wrap items-start justify-between gap-4 pb-5 mb-5 border-b editorial-border"
    }, /*#__PURE__*/React.createElement("div", {
      className: "space-y-1.5"
    }, /*#__PURE__*/React.createElement("div", {
      className: "flex items-center space-x-2"
    }, /*#__PURE__*/React.createElement("span", {
      className: "font-display text-xs font-extrabold uppercase text-forte"
    }, "ЭПИЗОД ", String(idx + 1).padStart(2, '0')), /*#__PURE__*/React.createElement("span", {
      className: "text-neutral-300"
    }, "•"), /*#__PURE__*/React.createElement("span", {
      className: "font-mono text-xs text-neutral-500"
    }, "Отметка ", v.timecode_sec, " сек")), /*#__PURE__*/React.createElement("h3", {
      className: "font-display text-lg sm:text-xl font-bold text-obsidian leading-snug"
    }, v.type)), /*#__PURE__*/React.createElement("button", {
      onClick: e => {
        e.stopPropagation();
        seekToSeconds(v.timecode_sec, idx);
      },
      className: "px-4 py-2.5 rounded-full bg-obsidian hover:bg-forte text-white font-mono text-xs font-bold transition cursor-pointer shrink-0"
    }, "▶ Таймкод: ", v.timecode_sec, " сек (", formatTimecode(v.timecode_sec), ")")), /*#__PURE__*/React.createElement("div", {
      className: "mb-5"
    }, /*#__PURE__*/React.createElement("div", {
      className: "font-mono text-[10px] uppercase tracking-widest text-neutral-500 font-bold mb-1.5"
    }, "ЧТО ИМЕННО ВИДНО НА ВИДЕО И ПОЧЕМУ ЭТО УКАЗЫВАЕТ НА НАРУШЕНИЕ"), /*#__PURE__*/React.createElement("p", {
      className: "text-sm sm:text-base text-obsidian leading-relaxed font-medium"
    }, observation)), /*#__PURE__*/React.createElement("div", {
      className: "p-5 rounded-2xl bg-forte-tint/70 border border-forte/20 mb-6"
    }, /*#__PURE__*/React.createElement("div", {
      className: "flex items-center justify-between mb-1.5"
    }, /*#__PURE__*/React.createElement("span", {
      className: "font-mono text-[10px] uppercase tracking-widest text-forte font-bold"
    }, label), url && /*#__PURE__*/React.createElement("a", {
      href: url,
      target: "_blank",
      rel: "noreferrer",
      onClick: e => e.stopPropagation(),
      className: "font-mono text-xs font-bold text-forte hover:underline"
    }, "adilet.zan.kz ↗")), /*#__PURE__*/React.createElement("p", {
      className: "text-xs sm:text-sm text-obsidian/90 leading-relaxed"
    }, law)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      className: "flex items-center justify-between mb-3"
    }, /*#__PURE__*/React.createElement("span", {
      className: "font-mono text-[10px] uppercase tracking-widest text-neutral-500 font-bold"
    }, "КАДРЫ-ДОКАЗАТЕЛЬСТВА ИЗ ФРАГМЕНТА (", v.evidence_frames?.length || 0, ")"), /*#__PURE__*/React.createElement("span", {
      className: "text-xs text-neutral-500"
    }, "Нажмите на кадр для увеличения")), /*#__PURE__*/React.createElement("div", {
      className: "grid grid-cols-2 sm:grid-cols-3 gap-3.5"
    }, (v.evidence_frames || []).map((frame, fIdx) => /*#__PURE__*/React.createElement("div", {
      key: fIdx,
      onClick: e => {
        e.stopPropagation();
        seekToSeconds(frame.timestamp_sec, idx);
        setLightboxFrame({
          src: getFrameSrc(frame.image_base64),
          timestamp: frame.timestamp_sec,
          type: v.type
        });
      },
      className: "group relative rounded-2xl overflow-hidden bg-obsidian border editorial-border h-48 flex items-center justify-center cursor-pointer shadow-sm"
    }, /*#__PURE__*/React.createElement("img", {
      src: getFrameSrc(frame.image_base64),
      alt: `Кадр ${frame.timestamp_sec} сек`,
      className: "w-full h-full object-contain group-hover:scale-105 transition duration-300"
    }), /*#__PURE__*/React.createElement("div", {
      className: "absolute bottom-2 left-2 right-2 flex items-center justify-between px-2.5 py-1 rounded-lg bg-black/80 backdrop-blur-sm text-white font-mono text-[11px]"
    }, /*#__PURE__*/React.createElement("span", null, "КАДР #", fIdx + 1), /*#__PURE__*/React.createElement("span", {
      className: "text-forte-vivid font-bold"
    }, frame.timestamp_sec, "s")))))));
  })))))), /*#__PURE__*/React.createElement("footer", {
    className: "max-w-6xl w-full mx-auto pt-8 mt-10 border-t editorial-border flex flex-col sm:flex-row items-center justify-between gap-2 font-mono text-[11px] text-neutral-500"
  }, /*#__PURE__*/React.createElement("span", null, "GASH.КОНТРОЛЬ // FORTEBANK DATATHON 26 · AI CASH COMPLIANCE"), /*#__PURE__*/React.createElement("span", null, "ИНФЕРЕНС НА ВЫДЕЛЕННОМ GPU · БЕЗ ВНЕШНЕГО AI API"))), lightboxFrame && /*#__PURE__*/React.createElement("div", {
    onClick: () => setLightboxFrame(null),
    className: "fixed inset-0 z-50 bg-obsidian/85 backdrop-blur-sm flex items-center justify-center p-4"
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    className: "bg-card rounded-[28px] max-w-4xl w-full overflow-hidden shadow-2xl border border-white/15"
  }, /*#__PURE__*/React.createElement("div", {
    className: "px-6 py-4 bg-obsidian text-white flex items-center justify-between gap-4"
  }, /*#__PURE__*/React.createElement("div", {
    className: "flex items-center space-x-3 min-w-0"
  }, /*#__PURE__*/React.createElement("span", {
    className: "px-3 py-1 rounded-full bg-forte font-mono text-xs font-bold shrink-0"
  }, lightboxFrame.timestamp, " сек"), /*#__PURE__*/React.createElement("span", {
    className: "font-display text-xs sm:text-sm font-bold truncate"
  }, lightboxFrame.type)), /*#__PURE__*/React.createElement("button", {
    onClick: () => setLightboxFrame(null),
    "aria-label": "Закрыть",
    className: "w-8 h-8 rounded-full bg-white/10 hover:bg-forte text-neutral-300 hover:text-white flex items-center justify-center transition cursor-pointer shrink-0 text-sm font-bold"
  }, "✕")), /*#__PURE__*/React.createElement("div", {
    className: "bg-black flex items-center justify-center max-h-[75vh]"
  }, /*#__PURE__*/React.createElement("img", {
    src: lightboxFrame.src,
    alt: "Кадр-доказательство",
    className: "max-h-[75vh] w-auto object-contain"
  })))));
}
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(/*#__PURE__*/React.createElement(App, null));
