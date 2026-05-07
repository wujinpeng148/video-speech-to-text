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
const copyResultBtn = document.getElementById("copyResultBtn");
const clearResultBtn = document.getElementById("clearResultBtn");

const toast = document.getElementById("toast");

let currentVideoFile = null;
let currentVideoId = null;
let detectedLanguageCode = null;
let translatedText = "";

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
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("video/")) {
        handleVideoUpload(file);
    } else {
        showToast("请拖入视频文件");
    }
});

videoInput.addEventListener("change", () => {
    const file = videoInput.files[0];
    if (file) handleVideoUpload(file);
});

reUploadBtn.addEventListener("click", () => {
    resetUpload();
});

// ========== 视频上传处理 ==========
function resetUpload() {
    currentVideoFile = null;
    currentVideoId = null;
    detectedLanguageCode = null;
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
}

// 步骤1：上传视频 → 检测语言
async function handleVideoUpload(file) {
    if (file.size > 500 * 1024 * 1024) {
        showToast("文件大小不能超过 500MB");
        return;
    }

    currentVideoFile = file;

    uploadArea.classList.add("hidden");
    uploadProgress.classList.remove("hidden");
    progressText.textContent = "正在上传视频并检测语言...";

    const formData = new FormData();
    formData.append("video", file);

    try {
        const response = await fetch("/api/detect-language", {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "语言检测失败");
        }

        currentVideoId = data.video_id;
        detectedLanguageCode = data.detected.mapped_code;

        // 隐藏上传进度，显示语言检测结果
        uploadProgress.classList.add("hidden");
        langDetectResult.classList.remove("hidden");

        const probPercent = Math.round(data.detected.probability * 100);
        detectedLangName.textContent = data.detected.name;
        detectedConfidence.textContent = "置信度 " + probPercent + "%";

        // 设置语言选择器默认值
        if (data.detected.mapped_code) {
            for (const opt of manualLangSelect.options) {
                if (opt.value === data.detected.mapped_code) {
                    opt.selected = true;
                    break;
                }
            }
        }

        // 自动设置翻译源语言
        if (data.detected.mapped_code) {
            sourceLang.value = data.detected.mapped_code;
        }

    } catch (error) {
        uploadProgress.classList.add("hidden");
        uploadArea.classList.remove("hidden");
        showToast(`语言检测失败: ${error.message}`);
        console.error("Detect error:", error);
    }
}

// 步骤2：确认语言 → 开始转录
startTranscribeBtn.addEventListener("click", async () => {
    if (!currentVideoId) {
        showToast("请先上传视频");
        return;
    }

    // 用户手动选择的语言优先，否则用检测到的语言
    let language = manualLangSelect.value || detectedLanguageCode || "auto";

    langDetectResult.classList.add("hidden");
    transcribeProgress.classList.remove("hidden");

    try {
        const response = await fetch("/api/transcribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                video_id: currentVideoId,
                language: language,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "语音识别失败");
        }

        // 显示转录结果
        sourceText.value = data.text;
        sourceText.disabled = false;
        sourceLang.disabled = false;
        translateBtn.disabled = false;
        proofreadBtn.disabled = false;
        updateWordCount();

        // 更新上传状态
        transcribeProgress.classList.add("hidden");
        uploadInfo.classList.remove("hidden");
        fileName.textContent = currentVideoFile ? currentVideoFile.name : "视频";

        // 同步检测到的语言到翻译源语言
        if (data.language && data.language !== "unknown") {
            const mapped = data.language;
            if (sourceLang.querySelector(`option[value="${mapped}"]`)) {
                sourceLang.value = mapped;
            }
        }

        showToast(`识别完成！共 ${data.text.length} 个字符`);

    } catch (error) {
        transcribeProgress.classList.add("hidden");
        langDetectResult.classList.remove("hidden");
        showToast(`语音识别失败: ${error.message}`);
        console.error("Transcribe error:", error);
    }
});

// ========== 文本校对 ==========
proofreadBtn.addEventListener("click", async () => {
    const text = sourceText.value.trim();
    if (!text) {
        showToast("请先输入或识别文本");
        return;
    }

    proofreadBtn.disabled = true;
    proofreadBtn.textContent = "校对中...";
    proofreadPanel.classList.add("hidden");

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

        renderProofreadResults(data);

    } catch (error) {
        showToast(`校对失败: ${error.message}`);
        console.error("Proofread error:", error);
    } finally {
        proofreadBtn.disabled = false;
        proofreadBtn.textContent = "🔍 校对";
    }
});

function renderProofreadResults(data) {
    proofreadList.innerHTML = "";

    if (!data.issues || data.issues.length === 0) {
        proofreadSummary.textContent = "✅ 未发现明显错别字";
        proofreadPanel.classList.remove("hidden");
        const emptyItem = document.createElement("div");
        emptyItem.className = "proofread-item";
        emptyItem.innerHTML = '<span style="color: var(--text-secondary)">文本看起来没问题，无需修改。</span>';
        proofreadList.appendChild(emptyItem);
        return;
    }

    proofreadSummary.textContent = `⚠️ 发现 ${data.total} 处疑似问题`;

    data.issues.forEach((issue, index) => {
        const item = document.createElement("div");
        item.className = "proofread-item";
        item.id = `proofread-issue-${index}`;

        const badgeType = issue.type === "typo" ? "错字" : "疑词";
        const badgeClass = issue.type === "typo" ? "typo" : "unknown_word";

        let suggestionHTML = "";
        if (issue.suggestion) {
            suggestionHTML = `<span class="issue-suggestion" title="点击替换">→ ${issue.suggestion}</span>`;
        }

        let altHTML = "";
        if (issue.alternatives && issue.alternatives.length > 1) {
            altHTML = `<div style="font-size:11px;color:var(--text-muted);margin-top:2px">其他可能: ${issue.alternatives.slice(1).join(" / ")}</div>`;
        }

        let actionHTML = "";
        if (issue.suggestion) {
            actionHTML = `
                <button class="issue-action accept" data-index="${index}">替换</button>
                <button class="issue-action ignore" data-index="${index}">忽略</button>
            `;
        }

        item.innerHTML = `
            <span class="issue-badge ${badgeClass}">${badgeType}</span>
            <div class="issue-info">
                <span class="issue-text">「${issue.original}」</span>
                ${suggestionHTML}
                <div class="issue-reason">${issue.reason}</div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:1px">上下文: ...${issue.context}...</div>
                ${altHTML}
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0">
                ${actionHTML}
            </div>
        `;

        proofreadList.appendChild(item);
    });

    proofreadPanel.classList.remove("hidden");

    // 绑定替换按钮事件
    proofreadList.querySelectorAll(".issue-action.accept").forEach(btn => {
        btn.addEventListener("click", () => {
            const idx = parseInt(btn.dataset.index);
            const issue = data.issues[idx];
            if (issue.suggestion) {
                const before = sourceText.value.substring(0, issue.start);
                const after = sourceText.value.substring(issue.end);
                sourceText.value = before + issue.suggestion + after;
                updateWordCount();
                // 移除该条
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
        btn.addEventListener("click", () => {
            const idx = parseInt(btn.dataset.index);
            const itemEl = document.getElementById(`proofread-issue-${idx}`);
            if (itemEl) itemEl.style.opacity = "0.4";
            btn.disabled = true;
            btn.textContent = "已忽略";
        });
    });
}

dismissProofreadBtn.addEventListener("click", () => {
    proofreadPanel.classList.add("hidden");
});

// ========== 文本编辑区 ==========
sourceText.addEventListener("input", () => {
    updateWordCount();
    translateBtn.disabled = !sourceText.value.trim();
    proofreadBtn.disabled = !sourceText.value.trim();
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
    if (sourceText.value && confirm("确定清空识别文本吗？")) {
        sourceText.value = "";
        updateWordCount();
        translateBtn.disabled = true;
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

        translatedText = data.translated_text;
        resultContent.textContent = translatedText;
        resultContent.classList.remove("hidden");
        resultPlaceholder.classList.add("hidden");

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

    // 如果有翻译结果，交换文本
    if (translatedText) {
        sourceText.value = translatedText;
        updateWordCount();
        translatedText = "";
        clearResult();
        showToast("已交换语言和文本");
    }
});

// ========== 翻译结果操作 ==========
copyResultBtn.addEventListener("click", () => {
    if (!translatedText) {
        showToast("没有可复制的翻译结果");
        return;
    }
    navigator.clipboard.writeText(translatedText).then(() => {
        showToast("翻译结果已复制到剪贴板");
    }).catch(() => {
        showToast("复制失败，请手动选择复制");
    });
});

clearResultBtn.addEventListener("click", () => {
    clearResult();
});

function clearResult() {
    translatedText = "";
    resultContent.textContent = "";
    resultContent.classList.add("hidden");
    resultPlaceholder.textContent = "翻译结果将显示在这里";
    resultPlaceholder.classList.remove("hidden");
}

// ========== 目标语言变更时自动翻译 ==========
let autoTranslateTimeout;
targetLang.addEventListener("change", () => {
    if (sourceText.value.trim()) {
        clearTimeout(autoTranslateTimeout);
        autoTranslateTimeout = setTimeout(performTranslation, 500);
    }
});
