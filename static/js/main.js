// ========== DOM 元素 ==========
const uploadArea = document.getElementById("uploadArea");
const videoInput = document.getElementById("videoInput");
const uploadProgress = document.getElementById("uploadProgress");
const progressText = document.getElementById("progressText");
const langDetectResult = document.getElementById("langDetectResult");
const detectedLangName = document.getElementById("detectedLangName");
const detectedConfidence = document.getElementById("detectedConfidence");
const manualLangSelect = document.getElementById("manualLangSelect");
const startTranscribeBtn = document.getElementById("startTranscribeBtn");
const transcribeProgress = document.getElementById("transcribeProgress");
const uploadInfo = document.getElementById("uploadInfo");
const fileName = document.getElementById("fileName");
const reUploadBtn = document.getElementById("reUploadBtn");

const sourceText = document.getElementById("sourceText");
const wordCount = document.getElementById("wordCount");
const proofreadBtn = document.getElementById("proofreadBtn");
const proofreadPanel = document.getElementById("proofreadPanel");
const proofreadSummary = document.getElementById("proofreadSummary");
const proofreadList = document.getElementById("proofreadList");
const dismissProofreadBtn = document.getElementById("dismissProofreadBtn");
const copySourceBtn = document.getElementById("copySourceBtn");
const clearSourceBtn = document.getElementById("clearSourceBtn");

const sourceLang = document.getElementById("sourceLang");
const targetLang = document.getElementById("targetLang");
const swapLangBtn = document.getElementById("swapLangBtn");
const translateBtn = document.getElementById("translateBtn");

const resultArea = document.getElementById("resultArea");
const resultPlaceholder = document.getElementById("resultPlaceholder");
const resultContent = document.getElementById("resultContent");
const translateProgress = document.getElementById("translateProgress");
const playTtsBtn = document.getElementById("playTtsBtn");
const ttsAudio = document.getElementById("ttsAudio");
const copyResultBtn = document.getElementById("copyResultBtn");
const clearResultBtn = document.getElementById("clearResultBtn");

const filmstripContainer = document.getElementById("filmstripContainer");
const filmstrip = document.getElementById("filmstrip");
const toast = document.getElementById("toast");

// ========== 多视频状态 ==========
let videos = [];           // 视频条目数组
let activeVideoId = null;  // 当前选中的视频 id
let isProcessing = false;  // 队列是否在处理中

// ========== Toast 提示 ==========
let toastTimer;
function showToast(message, duration = 2500) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("show");
    toastTimer = setTimeout(() => toast.classList.remove("show"), duration);
}

// ========== 上传区域事件 ==========
uploadArea.addEventListener("click", () => videoInput.click());

uploadArea.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadArea.classList.add("dragover");
});

uploadArea.addEventListener("dragleave", () => {
    uploadArea.classList.remove("dragover");
});

uploadArea.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadArea.classList.remove("dragover");
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith("video/"));
    if (files.length > 0) {
        handleFiles(files);
    } else {
        showToast("请拖入视频文件");
    }
});

videoInput.addEventListener("change", () => {
    const files = Array.from(videoInput.files).filter(f => f.type.startsWith("video/"));
    if (files.length > 0) handleFiles(files);
});

reUploadBtn.addEventListener("click", () => {
    const hasContent = videos.some(v => v.transcriptionText || v.translatedText);
    if (hasContent || sourceText.value.trim()) {
        if (!confirm("确定重新上传吗？\n\n所有视频的识别文本和翻译结果将被清空。")) return;
    }
    resetAll();
});


// ========== 视频上传处理 ==========
function resetAll() {
    videos = [];
    activeVideoId = null;
    isProcessing = false;
    videoInput.value = "";
    uploadArea.classList.remove("hidden");
    uploadProgress.classList.add("hidden");
    langDetectResult.classList.add("hidden");
    transcribeProgress.classList.add("hidden");
    uploadInfo.classList.add("hidden");
    manualLangSelect.value = "";
    sourceText.value = "";
    sourceText.disabled = true;
    sourceLang.disabled = true;
    translateBtn.disabled = true;
    proofreadBtn.disabled = true;
    proofreadPanel.classList.add("hidden");

    updateWordCount();
    clearResult();
    renderFilmstrip();
    const oldBanner = document.querySelector(".alert-banner");
    if (oldBanner) oldBanner.remove();
}

// ========== 缩略图生成 ==========
function generateThumbnail(file) {
    return new Promise((resolve) => {
        const video = document.createElement("video");
        const canvas = document.createElement("canvas");
        video.preload = "metadata";
        video.muted = true;
        video.playsInline = true;

        const cleanup = () => { URL.revokeObjectURL(video.src); };

        video.onloadeddata = () => { video.currentTime = 1; };
        video.onseeked = () => {
            const vw = video.videoWidth || 280;
            const vh = video.videoHeight || 160;
            const maxWidth = 280;
            canvas.width = maxWidth;
            canvas.height = Math.round(maxWidth * vh / vw);
            const ctx = canvas.getContext("2d");
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.7));
            cleanup();
        };
        video.onerror = () => {
            resolve(null);
            cleanup();
        };

        // 超时回退
        setTimeout(() => {
            if (video.readyState < 2) {
                resolve(null);
                cleanup();
            }
        }, 3000);

        video.src = URL.createObjectURL(file);
    });
}

// ========== 视频条目管理 ==========
function createVideoEntry(file, thumbnail) {
    return {
        id: "pending-" + Date.now() + "-" + Math.random().toString(36).substr(2, 6),
        file: file,
        fileName: file.name,
        thumbnail: thumbnail,
        status: "pending",
        detectedLanguage: null,
        languageProbabilities: [],
        transcriptionText: "",
        segments: [],
        translatedText: "",
        error: null,
        modelSize: null,
    };
}

function findVideoIndex(videoId) {
    return videos.findIndex(v => v.id === videoId);
}

function findVideoById(videoId) {
    return videos.find(v => v.id === videoId);
}

function getActiveVideo() {
    if (!activeVideoId) return null;
    return findVideoById(activeVideoId) || null;
}

function updateVideoStatus(videoId, status, extras = {}) {
    const v = findVideoById(videoId);
    if (!v) return;
    v.status = status;
    Object.assign(v, extras);
    renderFilmstrip();
    updateUIForActiveVideo();
}

function removeVideo(videoId) {
    const idx = findVideoIndex(videoId);
    if (idx === -1) return;
    const wasActive = (activeVideoId === videoId);
    videos.splice(idx, 1);
    if (wasActive) {
        if (videos.length > 0) {
            selectVideo(videos[Math.min(idx, videos.length - 1)].id);
        } else {
            activeVideoId = null;
            clearDisplayedContent();
            uploadArea.classList.remove("hidden");
        
        }
    }
    renderFilmstrip();
}

// ========== 多文件入口 ==========
async function handleFiles(files) {
    const fileArray = Array.from(files);
    const validFiles = fileArray.filter(f => {
        if (f.size > 500 * 1024 * 1024) {
            showToast(`"${f.name}" 超过 500MB 限制，已跳过`);
            return false;
        }
        if (!f.type.startsWith("video/")) {
            showToast(`"${f.name}" 不是视频文件，已跳过`);
            return false;
        }
        return true;
    });

    if (validFiles.length === 0) return;

    // 隐藏上传区域
    uploadArea.classList.add("hidden");

    // 生成缩略图（并行）
    const thumbnails = await Promise.all(
        validFiles.map(f => generateThumbnail(f))
    );

    // 添加到数组
    validFiles.forEach((file, i) => {
        const entry = createVideoEntry(file, thumbnails[i]);
        videos.push(entry);
    });

    renderFilmstrip();

    // 统一走队列自动处理
    showToast(`已添加 ${validFiles.length} 个视频，开始自动处理...`);
    startProcessingQueue();

    videoInput.value = "";
}

// 步骤2：确认语言 → 开始转录（单视频手动模式）
startTranscribeBtn.addEventListener("click", async () => {
    const pendingVideo = videos.find(v => v.status === "pending" && v.detectedLanguage);
    if (!pendingVideo) {
        showToast("请先上传视频并完成语言检测");
        return;
    }

    let language = manualLangSelect.value || pendingVideo.detectedLanguage?.mapped_code || "auto";

    langDetectResult.classList.add("hidden");
    transcribeProgress.classList.remove("hidden");

    try {
        // 更新状态为 transcribing
        updateVideoStatus(pendingVideo.id, "transcribing");

        const response = await fetch("/api/transcribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                video_id: pendingVideo.id,
                language: language,
                model_size: "small",
            }),
        });

        const data = await response.json();

        if (!response.ok) throw new Error(data.error || "语音识别失败");

        // 更新视频条目
        updateVideoStatus(pendingVideo.id, "done", {
            transcriptionText: data.text,
            segments: data.segments || [],
            modelSize: data.model_size,
            audioStem: data.audio_stem || pendingVideo.id,
        });

        // 选中该视频
        selectVideo(pendingVideo.id);

        // UI 更新
        transcribeProgress.classList.add("hidden");
        uploadInfo.classList.remove("hidden");
        fileName.textContent = pendingVideo.fileName;

        if (data.language && data.language !== "unknown") {
            const mapped = data.language;
            if (sourceLang.querySelector(`option[value="${mapped}"]`)) {
                sourceLang.value = mapped;
            }
        }

        showToast(`识别完成！共 ${data.text.length} 个字符，模型: ${data.model_size || 'small'}`);
        setTimeout(() => performProofread(true), 300);

    } catch (error) {
        updateVideoStatus(pendingVideo.id, "error", { error: error.message });
        transcribeProgress.classList.add("hidden");
        langDetectResult.classList.remove("hidden");
        showToast(`语音识别失败: ${error.message}`);
    }
});

// ========== 胶片条渲染 ==========
function renderFilmstrip() {
    filmstrip.innerHTML = "";

    if (videos.length === 0) {
        filmstripContainer.classList.add("hidden");
    
        return;
    }

    filmstripContainer.classList.remove("hidden");

    videos.forEach(v => {
        const card = document.createElement("div");
        card.className = `video-thumbnail${v.id === activeVideoId ? " active" : ""}${v.status === "error" ? " error" : ""}`;
        card.dataset.videoId = v.id;
        card.title = v.fileName;

        // 缩略图
        const imgWrap = document.createElement("div");
        imgWrap.className = "thumb-img-wrap";
        if (v.thumbnail) {
            const img = document.createElement("img");
            img.src = v.thumbnail;
            img.alt = v.fileName;
            imgWrap.appendChild(img);
        } else {
            const placeholder = document.createElement("span");
            placeholder.className = "thumb-placeholder";
            placeholder.textContent = "🎬";
            imgWrap.appendChild(placeholder);
        }
        card.appendChild(imgWrap);

        // 状态徽章
        if (v.status !== "pending") {
            const badge = document.createElement("span");
            badge.className = `status-badge ${v.status}`;
            const badgeText = {
                detecting: "检测中", transcribing: "识别中",
                done: "✓", error: "✗"
            };
            badge.textContent = badgeText[v.status] || "";
            card.appendChild(badge);
        }

        // 信息栏
        const info = document.createElement("div");
        info.className = "thumb-info";
        const nameEl = document.createElement("div");
        nameEl.className = "thumb-name";
        nameEl.textContent = v.fileName;
        const statusEl = document.createElement("div");
        statusEl.className = "thumb-status";
        const statusText = {
            pending: "等待处理",
            detecting: "语言检测中...",
            transcribing: "语音识别中...",
            done: `已完成 (${v.transcriptionText.length}字)`,
            error: v.error || "处理失败"
        };
        statusEl.textContent = statusText[v.status] || "";
        info.appendChild(nameEl);
        info.appendChild(statusEl);
        card.appendChild(info);

        // 删除按钮（处理中不可删）
        if (v.status !== "detecting" && v.status !== "transcribing") {
            const removeBtn = document.createElement("button");
            removeBtn.className = "thumb-remove";
            removeBtn.textContent = "×";
            removeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                removeVideo(v.id);
            });
            card.appendChild(removeBtn);
        }

        // 点击选中
        card.addEventListener("click", () => {
            if (v.status === "done" || v.status === "error") {
                selectVideo(v.id);
            }
        });

        filmstrip.appendChild(card);
    });

    // "+" 添加更多
    const addCard = document.createElement("div");
    addCard.className = "video-thumbnail add-more";
    addCard.innerHTML = `<span class="add-icon">+</span><span>添加视频</span>`;
    addCard.addEventListener("click", () => videoInput.click());
    filmstrip.appendChild(addCard);
}

// ========== 视频切换 ==========
function selectVideo(videoId) {
    // 保存当前编辑内容
    if (activeVideoId) {
        const prev = findVideoById(activeVideoId);
        if (prev && prev.status === "done") {
            prev.transcriptionText = sourceText.value;
        }
    }

    activeVideoId = videoId;
    const v = findVideoById(videoId);
    if (!v) return;

    sourceText.value = v.transcriptionText;
    sourceText.disabled = (v.status !== "done");
    sourceLang.disabled = (v.status !== "done");
    translateBtn.disabled = !v.transcriptionText.trim();
    proofreadBtn.disabled = !v.transcriptionText.trim();
    updateWordCount();

    // 语言同步
    if (v.detectedLanguage?.mapped_code) {
        if (sourceLang.querySelector(`option[value="${v.detectedLanguage.mapped_code}"]`)) {
            sourceLang.value = v.detectedLanguage.mapped_code;
        }
    }

    // 翻译结果
    if (v.translatedText) {
        resultContent.textContent = v.translatedText;
        resultContent.classList.remove("hidden");
        resultPlaceholder.classList.add("hidden");
        playTtsBtn.disabled = false;
        // 切换视频时重置 TTS（不同视频需要重新生成语音）
        ttsAudio.classList.add("hidden");
        playTtsBtn.textContent = "🔊 播放";
        ttsLoaded = false;
    } else {
        resultContent.classList.add("hidden");
        resultPlaceholder.classList.remove("hidden");
        resultPlaceholder.textContent = "翻译结果将显示在这里";
        playTtsBtn.disabled = true;
        playTtsBtn.textContent = "🔊 播放";
        ttsLoaded = false;
    }

    // 关闭校对面板
    proofreadPanel.classList.add("hidden");
    const oldBanner = document.querySelector(".alert-banner");
    if (oldBanner) oldBanner.remove();

    // 更新上传信息
    uploadInfo.classList.remove("hidden");
    fileName.textContent = v.fileName;

    // 隐藏语言检测面板
    langDetectResult.classList.add("hidden");

    renderFilmstrip();
}

function clearDisplayedContent() {
    activeVideoId = null;
    sourceText.value = "";
    sourceText.disabled = true;
    sourceLang.disabled = true;
    translateBtn.disabled = true;
    proofreadBtn.disabled = true;
    proofreadPanel.classList.add("hidden");
    clearResult();
    uploadInfo.classList.add("hidden");
    updateWordCount();
    const oldBanner = document.querySelector(".alert-banner");
    if (oldBanner) oldBanner.remove();
}

function updateUIForActiveVideo() {
    if (!activeVideoId) return;
    const v = getActiveVideo();
    if (!v) return;
    if (document.activeElement !== sourceText) {
        sourceText.value = v.transcriptionText;
    }
    updateWordCount();
}

// ========== 队列顺序处理 ==========
async function startProcessingQueue() {
    if (isProcessing) return;
    isProcessing = true;

    let pendingVideos = videos.filter(v => v.status === "pending");

    while (pendingVideos.length > 0) {
        for (const v of pendingVideos) {
            try {
                // 步骤1：上传 + 语言检测
                updateVideoStatus(v.id, "detecting");
                const detectResult = await detectLanguageForVideo(v);
                if (!detectResult || detectResult.error) {
                    throw new Error(detectResult?.error || "语言检测失败");
                }

                // 更新为后端真实的 video_id
                const oldId = v.id;
                v.id = detectResult.video_id;
                v.detectedLanguage = detectResult.detected;
                v.languageProbabilities = detectResult.all_languages || [];
                if (activeVideoId === oldId) activeVideoId = v.id;

                // 步骤2：转录
                updateVideoStatus(v.id, "transcribing");
                const transResult = await transcribeVideo(v);
                if (!transResult || transResult.error) {
                    throw new Error(transResult?.error || "语音识别失败");
                }

                updateVideoStatus(v.id, "done", {
                    transcriptionText: transResult.text,
                    segments: transResult.segments || [],
                    modelSize: transResult.model_size,
                    audioStem: transResult.audio_stem || v.id,
                });

                // 首个完成的视频自动选中
                if (!activeVideoId) {
                    selectVideo(v.id);
                    uploadInfo.classList.remove("hidden");
                    fileName.textContent = v.fileName;
                }

            } catch (err) {
                updateVideoStatus(v.id, "error", { error: err.message });
                console.error(`视频 "${v.fileName}" 处理失败:`, err);
            }
        }

        // 检查是否有在处理期间新加入的视频
        pendingVideos = videos.filter(v => v.status === "pending");
    }

    isProcessing = false;
    showToast("所有视频处理完毕！");
}

async function detectLanguageForVideo(videoEntry) {
    const formData = new FormData();
    formData.append("video", videoEntry.file);

    const resp = await fetch("/api/detect-language", {
        method: "POST",
        body: formData,
    });
    return await resp.json();
}

async function transcribeVideo(videoEntry) {
    const language = videoEntry.detectedLanguage?.mapped_code || "auto";
    const resp = await fetch("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            video_id: videoEntry.id,
            language: language,
            model_size: "medium",
        }),
    });
    return await resp.json();
}

// ========== 文本校对 ==========
proofreadBtn.addEventListener("click", () => performProofread(false));

async function performProofread(isAuto) {
    const text = sourceText.value.trim();
    if (!text) {
        if (!isAuto) showToast("请先输入或识别文本");
        return;
    }

    if (!isAuto) {
        proofreadBtn.disabled = true;
        proofreadBtn.textContent = "校对中...";
    }
    proofreadPanel.classList.add("hidden");
    // 隐藏旧提醒框
    const oldBanner = document.querySelector(".alert-banner");
    if (oldBanner) oldBanner.remove();
    const oldIndicator = document.querySelector(".auto-proofread-indicator");
    if (oldIndicator) oldIndicator.remove();

    // 自动校对的加载提示
    if (isAuto && data.issues === undefined) {
        const indicator = document.createElement("div");
        indicator.className = "auto-proofread-indicator";
        indicator.innerHTML = '<div class="spinner spinner-sm"></div><span>智能校对中...</span>';
        proofreadPanel.parentNode.insertBefore(indicator, proofreadPanel);
    }

    try {
        const response = await fetch("/api/proofread", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "校对失败");
        }

        // 移除加载指示器
        const indicator = document.querySelector(".auto-proofread-indicator");
        if (indicator) indicator.remove();

        // 显示提醒框
        showAlertBanner(data);

        // 渲染详细列表
        renderProofreadResults(data);

    } catch (error) {
        const indicator = document.querySelector(".auto-proofread-indicator");
        if (indicator) indicator.remove();
        if (!isAuto) {
            showToast(`校对失败: ${error.message}`);
            console.error("Proofread error:", error);
        }
    } finally {
        proofreadBtn.disabled = false;
        proofreadBtn.textContent = "🔍 校对";
    }
}

// ========== 醒目的提醒框 ==========
function showAlertBanner(data) {
    const summary = data.summary;
    const stats = data.stats;

    let iconSymbol = "";
    let titleText = "";
    if (summary.level === "clean") {
        iconSymbol = "✅";
        titleText = "文本检查通过";
    } else if (summary.level === "error") {
        iconSymbol = "🚫";
        titleText = "发现语法错误，建议修改";
    } else if (summary.level === "warning") {
        iconSymbol = "⚠️";
        titleText = "发现疑似问题，请关注";
    } else {
        iconSymbol = "💡";
        titleText = "优化建议";
    }

    const banner = document.createElement("div");
    banner.className = `alert-banner ${summary.level}`;
    banner.id = "alertBanner";

    let statsHTML = "";
    if (stats.error > 0) {
        statsHTML += `<div class="alert-stat num-error">❌ ${stats.error} 错误</div>`;
    }
    if (stats.warning > 0) {
        statsHTML += `<div class="alert-stat num-warning">⚠️ ${stats.warning} 警告</div>`;
    }
    if (stats.suggestion > 0) {
        statsHTML += `<div class="alert-stat num-suggestion">💡 ${stats.suggestion} 建议</div>`;
    }

    banner.innerHTML = `
        <div class="alert-icon">${iconSymbol}</div>
        <div class="alert-body">
            <div class="alert-title">${titleText}</div>
            <div class="alert-desc">${summary.text}</div>
        </div>
        ${statsHTML ? `<div class="alert-stats">${statsHTML}</div>` : ""}
        <button class="alert-close" id="dismissAlertBtn" title="关闭提醒">×</button>
    `;

    // 插入到编辑区顶部
    const editorSection = document.querySelector(".editor-section");
    const sectionHeader = editorSection.querySelector(".section-header");
    sectionHeader.after(banner);

    // 关闭按钮
    document.getElementById("dismissAlertBtn").addEventListener("click", () => {
        banner.style.animation = "fadeOut 0.2s ease forwards";
        setTimeout(() => banner.remove(), 200);
    });
}

function renderProofreadResults(data) {
    proofreadList.innerHTML = "";

    if (!data.issues || data.issues.length === 0) {
        proofreadSummary.textContent = "✅ 未发现明显问题";
        proofreadPanel.classList.remove("hidden");
        const emptyItem = document.createElement("div");
        emptyItem.className = "proofread-item";
        emptyItem.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">✅ 文本看起来没问题，无需修改。</span>';
        proofreadList.appendChild(emptyItem);
        return;
    }

    proofreadSummary.textContent = `🔍 发现 ${data.total} 处问题（点击可定位到原文）`;

    data.issues.forEach((issue, index) => {
        const item = document.createElement("div");
        item.className = "proofread-item clickable";
        item.id = `proofread-issue-${index}`;
        item.title = "点击定位到原文中的问题位置";

        // 类型徽章
        const typeLabels = {
            typo: "错字", unknown_word: "疑词", redundancy: "冗余",
            grammar: "语法", punctuation: "标点", collocation: "搭配",
        };
        const badgeLabel = typeLabels[issue.type] || issue.type;
        const badgeClass = issue.type;

        // 严重程度圆点
        let severityDot = "";
        if (issue.severity) {
            severityDot = `<span class="severity-dot severity-${issue.severity}" title="${issue.severity}"></span>`;
        }

        let suggestionHTML = "";
        if (issue.suggestion) {
            suggestionHTML = `<span class="issue-suggestion" title="点击替换">→ ${issue.suggestion}</span>`;
        }

        let altHTML = "";
        if (issue.alternatives && issue.alternatives.length > 1) {
            altHTML = `<div style="font-size:11px;color:var(--text-muted);margin-top:2px">其他可能: ${issue.alternatives.slice(1).join(" / ")}</div>`;
        }

        let actionHTML = "";
        if (issue.suggestion && issue.suggestion !== "请检查标点使用" && issue.type !== "grammar") {
            actionHTML = `
                <button class="issue-action accept" data-index="${index}">替换</button>
                <button class="issue-action ignore" data-index="${index}">忽略</button>
            `;
        } else if (issue.type === "grammar" || issue.type === "punctuation") {
            actionHTML = `<button class="issue-action ignore" data-index="${index}">忽略</button>`;
        }

        // 定位图标
        const locateIcon = `<span style="flex-shrink:0;font-size:14px;color:var(--text-muted);margin-left:4px" title="点击定位">📍</span>`;

        item.innerHTML = `
            ${severityDot}
            <span class="issue-badge ${badgeClass}">${badgeLabel}</span>
            <div class="issue-info">
                <span class="issue-text">「${issue.original}」</span>
                ${suggestionHTML}
                <div class="issue-reason">${issue.reason}</div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:1px">上下文: ...${issue.context}...</div>
                ${altHTML}
            </div>
            ${locateIcon}
            <div style="display:flex;gap:6px;flex-shrink:0">
                ${actionHTML}
            </div>
        `;

        // 整行点击 → 定位到原文
        item.addEventListener("click", (e) => {
            // 不拦截按钮自身的点击
            if (e.target.tagName === "BUTTON" || e.target.closest(".issue-suggestion")) return;
            locateIssueInText(issue, index);
        });

        proofreadList.appendChild(item);
    });

    proofreadPanel.classList.remove("hidden");

    // 绑定替换按钮事件
    proofreadList.querySelectorAll(".issue-action.accept").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const issue = data.issues[idx];
            if (issue.suggestion) {
                const before = sourceText.value.substring(0, issue.start);
                const after = sourceText.value.substring(issue.end);
                sourceText.value = before + issue.suggestion + after;
                updateWordCount();
                const itemEl = document.getElementById(`proofread-issue-${idx}`);
                if (itemEl) itemEl.style.opacity = "0.4";
                btn.disabled = true;
                btn.textContent = "已替换";
                showToast("已替换");
            }
        });
    });

    // 绑定忽略按钮事件
    proofreadList.querySelectorAll(".issue-action.ignore").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const itemEl = document.getElementById(`proofread-issue-${idx}`);
            if (itemEl) itemEl.style.opacity = "0.4";
            btn.disabled = true;
            btn.textContent = "已忽略";
        });
    });

    // suggestion 点击 → 替换
    proofreadList.querySelectorAll(".issue-suggestion").forEach(sug => {
        sug.addEventListener("click", (e) => {
            e.stopPropagation();
            const itemEl = sug.closest(".proofread-item");
            const acceptBtn = itemEl.querySelector(".issue-action.accept");
            if (acceptBtn) acceptBtn.click();
        });
    });
}

// ========== 定位到原文问题位置 ==========
function locateIssueInText(issue, index) {
    sourceText.focus();

    // 选中问题文本
    sourceText.setSelectionRange(issue.start, issue.end);

    // 计算行高，滚动到可见区域
    const textarea = sourceText;
    const textBefore = textarea.value.substring(0, issue.start);
    const lineHeight = parseFloat(getComputedStyle(textarea).lineHeight) || 22;
    const paddingTop = parseFloat(getComputedStyle(textarea).paddingTop) || 16;
    const lines = textBefore.split("\n").length;
    const targetScroll = (lines - 1) * lineHeight + paddingTop - 60; // 60px 偏移，避免太贴顶
    textarea.scrollTop = Math.max(0, targetScroll);

    // 添加脉冲高亮动画
    textarea.classList.remove("highlight-pulse");
    void textarea.offsetWidth; // 强制回流
    textarea.classList.add("highlight-pulse");

    // 当前点击的条目高亮
    const allItems = proofreadList.querySelectorAll(".proofread-item.clickable");
    allItems.forEach(el => el.style.background = "");
    const currentItem = document.getElementById(`proofread-issue-${index}`);
    if (currentItem) {
        currentItem.style.background = "#fde68a";
        setTimeout(() => { currentItem.style.background = ""; }, 2000);
    }
}

dismissProofreadBtn.addEventListener("click", () => {
    proofreadPanel.classList.add("hidden");
});

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

// ========== 文本编辑区 ==========
sourceText.addEventListener("input", () => {
    updateWordCount();
    translateBtn.disabled = !sourceText.value.trim();
    proofreadBtn.disabled = !sourceText.value.trim();
    // 保存编辑到当前视频
    const active = getActiveVideo();
    if (active && active.status === "done") {
        active.transcriptionText = sourceText.value;
        active.translatedText = "";  // 编辑后翻译失效
        clearResult();
    }
});

copySourceBtn.addEventListener("click", () => {
    if (!sourceText.value.trim()) {
        showToast("没有可复制的内容");
        return;
    }
    navigator.clipboard.writeText(sourceText.value).then(() => {
        showToast("已复制到剪贴板");
    }).catch(() => {
        sourceText.select();
        showToast("请手动复制 (Ctrl+C)");
    });
});

clearSourceBtn.addEventListener("click", () => {
    const active = getActiveVideo();
    if (sourceText.value && confirm("确定清空当前视频的识别文本吗？")) {
        if (active && active.status === "done") {
            active.transcriptionText = "";
            active.translatedText = "";
        }
        sourceText.value = "";
        updateWordCount();
        translateBtn.disabled = true;
        proofreadBtn.disabled = true;
        clearResult();
        renderFilmstrip();
    }
});

function updateWordCount() {
    const text = sourceText.value.trim();
    const count = text.length;
    wordCount.textContent = `${count} 字`;
}

// ========== 翻译 ==========
translateBtn.addEventListener("click", performTranslation);

// 当源文本有内容时，也可以直接按 Ctrl+Enter 翻译
sourceText.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        performTranslation();
    }
});

async function performTranslation() {
    const text = sourceText.value.trim();
    if (!text) {
        showToast("请输入或上传需要翻译的文本");
        return;
    }

    // 更新 UI
    translateBtn.disabled = true;
    translateProgress.classList.remove("hidden");
    resultPlaceholder.classList.add("hidden");
    resultContent.classList.add("hidden");

    try {
        const response = await fetch("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text: text,
                source: sourceLang.value,
                target: targetLang.value,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "翻译失败");
        }

        const translatedText = data.translated_text;
        resultContent.textContent = translatedText;
        resultContent.classList.remove("hidden");
        resultPlaceholder.classList.add("hidden");
        playTtsBtn.disabled = false;

        // 保存翻译到当前视频
        const active = getActiveVideo();
        if (active) {
            active.translatedText = translatedText;
        }

        const targetName = targetLang.options[targetLang.selectedIndex].text;
        showToast(`翻译完成 → ${targetName}`);

    } catch (error) {
        resultPlaceholder.textContent = `翻译失败: ${error.message}`;
        resultPlaceholder.classList.remove("hidden");
        resultContent.classList.add("hidden");
        showToast(`翻译失败: ${error.message}`);
        console.error("Translation error:", error);
    } finally {
        translateBtn.disabled = false;
        translateProgress.classList.add("hidden");
    }
}

// ========== 交换语言 ==========
swapLangBtn.addEventListener("click", () => {
    if (sourceLang.value === "auto") {
        showToast("自动检测模式下无法交换语言");
        return;
    }

    const temp = sourceLang.value;
    sourceLang.value = targetLang.value;
    targetLang.value = temp;

    const active = getActiveVideo();
    const activeTranslation = active?.translatedText || "";

    if (activeTranslation) {
        sourceText.value = activeTranslation;
        updateWordCount();
        if (active) {
            active.transcriptionText = activeTranslation;
            active.translatedText = "";
        }
        clearResult();
        showToast("已交换语言和文本");
    }
});

// ========== TTS 播放/暂停翻译语音 ==========
let ttsLoaded = false;

ttsAudio.addEventListener("ended", () => {
    playTtsBtn.textContent = "🔊 播放";
    ttsLoaded = false;
});

ttsAudio.addEventListener("pause", () => {
    if (!ttsAudio.ended) {
        playTtsBtn.textContent = "▶ 继续";
    }
});

playTtsBtn.addEventListener("click", async () => {
    // 已加载 → 切换播放/暂停
    if (ttsLoaded) {
        if (ttsAudio.paused) {
            await ttsAudio.play();
            playTtsBtn.textContent = "⏸ 暂停";
        } else {
            ttsAudio.pause();
        }
        return;
    }

    const active = getActiveVideo();
    const text = active?.translatedText || "";
    if (!text) {
        showToast("请先翻译文本");
        return;
    }

    playTtsBtn.disabled = true;
    playTtsBtn.textContent = "生成中...";

    try {
        const response = await fetch("/api/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text: text,
                target_lang: targetLang.value,
            }),
        });
        const data = await response.json();

        if (!data.success) throw new Error(data.error || "TTS 失败");

        ttsAudio.src = "data:audio/mp3;base64," + data.audio_base64;
        ttsAudio.classList.remove("hidden");
        await ttsAudio.play();
        playTtsBtn.textContent = "⏸ 暂停";
        ttsLoaded = true;

    } catch (error) {
        showToast(`语音生成失败: ${error.message}`);
    } finally {
        playTtsBtn.disabled = false;
    }
});

// ========== 翻译结果操作 ==========
copyResultBtn.addEventListener("click", () => {
    const active = getActiveVideo();
    const textToCopy = active?.translatedText || "";
    if (!textToCopy) {
        showToast("没有可复制的翻译结果");
        return;
    }
    navigator.clipboard.writeText(textToCopy).then(() => {
        showToast("翻译结果已复制到剪贴板");
    }).catch(() => {
        showToast("复制失败，请手动选择复制");
    });
});

clearResultBtn.addEventListener("click", () => {
    clearResult();
});

function clearResult() {
    const active = getActiveVideo();
    if (active) active.translatedText = "";
    resultContent.textContent = "";
    resultContent.classList.add("hidden");
    resultPlaceholder.textContent = "翻译结果将显示在这里";
    resultPlaceholder.classList.remove("hidden");
    playTtsBtn.disabled = true;
    playTtsBtn.textContent = "🔊 播放";
    ttsAudio.classList.add("hidden");
    ttsLoaded = false;
}

// ========== 目标语言变更时自动翻译 ==========
let autoTranslateTimeout;
targetLang.addEventListener("change", () => {
    if (sourceText.value.trim()) {
        clearTimeout(autoTranslateTimeout);
        autoTranslateTimeout = setTimeout(performTranslation, 500);
    }
});
