        // ===================== 全局配置 =====================
        // 后端服务地址，与FastAPI监听端口一致
        const BACKEND = "";
        let authMode = "login";
        let interviewAbortController = null;
        let assistantAbortController = null;
        let uploadedResumeFile = null;
        let generatedResumeText = "";

        // ===================== 通用请求封装函数 =====================
        /**
         * 统一fetch请求封装，捕获后端未启动、服务异常报错
         * @param {string} url 接口路径（不带域名）
         * @param {object} opt fetch配置（method/headers/body等）
         * @returns {Promise<any>} 后端返回json数据
         */
        async function request(url, opt = {}) {
            try {
                // 拼接完整请求地址
                const res = await fetch(`${BACKEND}${url}`, { credentials: "include", ...opt });
                // 非200状态码抛出异常
                if (res.status === 401) {
                    showAuthOverlay();
                    throw new Error("登录状态已失效，请重新登录");
                }
                if (!res.ok) {
                    const errorData = await res.json().catch(() => ({}));
                    throw new Error(errorData.detail || "服务异常 " + res.status);
                }
                // 解析json返回
                return await res.json();
            } catch (err) {
                // 无法连接后端时友好提示
                if (err.message.includes("Failed to fetch")) {
                    throw new Error("后端服务未启动，请先启动后端服务");
                }
                throw err;
            }
        }

        async function streamPost(url, payload, controller, onEvent) {
            const response = await fetch(BACKEND + url, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                signal: controller.signal
            });
            if (response.status === 401) {
                showAuthOverlay();
                throw new Error("登录状态已失效，请重新登录");
            }
            if (!response.ok || !response.body) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || "流式请求失败");
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            while (true) {
                const result = await reader.read();
                if (result.done) break;
                buffer += decoder.decode(result.value, { stream: true });
                let boundary = buffer.indexOf("\n\n");
                while (boundary !== -1) {
                    const event = buffer.slice(0, boundary);
                    buffer = buffer.slice(boundary + 2);
                    const dataLine = event.split("\n").find(line => line.startsWith("data:"));
                    if (dataLine) onEvent(dataLine.slice(5));
                    boundary = buffer.indexOf("\n\n");
                }
            }
        }

        function showAuthOverlay() {
            closeAllSSE();
            document.getElementById("authOverlay").classList.add("visible");
            document.getElementById("userPanel").hidden = true;
            document.getElementById("authPassword").value = "";
        }

        function hideAuthOverlay(username) {
            document.getElementById("authOverlay").classList.remove("visible");
            document.getElementById("currentUsername").innerText = username;
            document.getElementById("userPanel").hidden = false;
            document.getElementById("authError").style.display = "none";
            document.getElementById("authForm").reset();
        }

        function toggleAuthMode() {
            authMode = authMode === "login" ? "register" : "login";
            const isRegister = authMode === "register";
            document.getElementById("authTitle").innerText = isRegister ? "注册 Career Coach" : "登录 Career Coach";
            document.getElementById("authSubtitle").innerText = isRegister ? "创建账号后即可开始使用服务。" : "登录后即可使用简历优化与模拟面试服务。";
            document.getElementById("authSubmitBtn").innerText = isRegister ? "注册并登录" : "登录";
            document.getElementById("authSwitchBtn").innerText = isRegister ? "已有账号？立即登录" : "没有账号？立即注册";
            document.getElementById("authError").style.display = "none";
            document.getElementById("authPassword").autocomplete = isRegister ? "new-password" : "current-password";
        }

        async function submitAuth(event) {
            event.preventDefault();
            const username = document.getElementById("authUsername").value.trim();
            const password = document.getElementById("authPassword").value;
            const submitBtn = document.getElementById("authSubmitBtn");
            const error = document.getElementById("authError");
            submitBtn.disabled = true;
            error.style.display = "none";
            try {
                const endpoint = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
                const response = await fetch(BACKEND + endpoint, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || "认证失败，请稍后重试");
                hideAuthOverlay(username);
            } catch (err) {
                error.innerText = err.message;
                error.style.display = "block";
            } finally {
                submitBtn.disabled = false;
            }
        }

        async function loadCurrentUser() {
            try {
                const response = await fetch(BACKEND + "/api/auth/me", { credentials: "include" });
                if (!response.ok) throw new Error("unauthenticated");
                const data = await response.json();
                hideAuthOverlay(data.data.username);
            } catch (_) {
                showAuthOverlay();
            }
        }

        async function logout() {
            try {
                await fetch(BACKEND + "/api/auth/logout", { method: "POST", credentials: "include" });
            } finally {
                showAuthOverlay();
            }
        }

        // ===================== 浏览器语音识别模块 =====================
        // 兼容chrome/webkit语音识别API
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        let recognition = null; // 语音识别实例
        let isRecording = false; // 录音状态标记

        /**
         * 初始化语音识别对象，配置中文、持续识别
         */
        function initSpeechRecognition() {
            // 浏览器不支持则隐藏语音按钮
            if (!SpeechRecognition) {
                document.getElementById("interviewVoiceBtn").style.display = "none";
                return;
            }

            recognition = new SpeechRecognition();
            recognition.continuous = true; // 持续识别
            recognition.interimResults = true; // 返回中间识别结果
            recognition.lang = "zh-CN"; // 识别中文

            // 识别结果回调，实时填充输入框
            recognition.onresult = function(event) {
                let transcript = "";
                // 拼接所有识别分片文本
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    transcript += event.results[i][0].transcript;
                }
                document.getElementById("interviewInput").value = transcript;
            };

            // 识别错误监听
            recognition.onerror = function(event) {
                console.error("语音识别错误:", event.error);
                // 无麦克风权限提示
                if (event.error === "not-allowed") {
                    alert("请允许麦克风权限以使用语音输入功能");
                }
                stopRecording();
            };

            // 识别自动结束时，如果正在录音则重启
            recognition.onend = function() {
                if (isRecording) {
                    recognition.start();
                }
            };
        }

        /**
         * 切换录音启停状态（按钮点击触发）
         */
        function toggleInterviewVoice() {
            if (!SpeechRecognition) {
                alert("当前浏览器不支持语音识别功能，请使用 Chrome 或 Safari 浏览器");
                return;
            }
            // 未初始化则先初始化
            if (!recognition) {
                initSpeechRecognition();
            }
            // 切换启停
            if (isRecording) {
                stopRecording();
            } else {
                startRecording();
            }
        }

        /**
         * 开启麦克风录音
         */
        function startRecording() {
            try {
                recognition.start();
                isRecording = true;
                const btn = document.getElementById("interviewVoiceBtn");
                btn.classList.add("recording");
                btn.innerHTML = "⏹️";
            } catch (e) {
                console.error("启动录音失败:", e);
                alert("启动录音失败，请重试");
            }
        }

        /**
         * 关闭麦克风录音，重置按钮样式
         */
        function stopRecording() {
            if (!recognition) return;
            try {
                recognition.stop();
                isRecording = false;
                const btn = document.getElementById("interviewVoiceBtn");
                btn.classList.remove("recording");
                // 恢复麦克风图标svg
                btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" d="M15.064 2.987a1 1 0 0 1 1 1v16.026a1 1 0 0 1-2 0V3.987a1 1 0 0 1 1-1M8.937 6.182a1 1 0 0 1 1 1v9.636a1 1 0 0 1-2 0V7.182a1 1 0 0 1 1-1M2.809 7.974a1 1 0 0 1 1 1v6.052a1 1 0 0 1-2 0V8.974a1 1 0 0 1 1-1M21.191 7.974a1 1 0 0 1 1 1v6.052a1 1 0 0 1-2 0V8.974a1 1 0 0 1 1-1"></path></svg>`;
            } catch (e) {
                console.error("停止录音失败:", e);
            }
        }

        // ===================== 全局会话状态变量 =====================
        // 面试会话ID
        let interviewSessionId = "";
        // 面试AI是否正在流式输出标记，防止重复发送
        let interviewIsTyping = false;
        let interviewCompleted = false;
        let currentInterviewReport = null;
        let currentInterviewHistoryId = null;
        // AI助手会话ID
        let chatSessionId = "";
        // AI助手是否正在流式输出标记
        let chatIsTyping = false;

        /**
         * 关闭所有SSE长连接、停止录音，切换页面时调用，释放资源
         */
        function closeAllSSE() {
            // 关闭面试流式连接
            if (interviewAbortController) {
                interviewAbortController.abort();
                interviewAbortController = null;
            }
            // 关闭AI助手流式连接
            if (assistantAbortController) {
                assistantAbortController.abort();
                assistantAbortController = null;
            }
            // 停止麦克风录音
            stopRecording();
        }

        // ===================== 页面切换逻辑 =====================
        /**
         * 切换左侧导航对应页面
         * @param {string} page 页面标识 resume/interview/knowledge/assistant
         */
        function switchPage(page) {
            // 切换页面前关闭所有长连接与录音
            closeAllSSE();
            const pages = ['resume', 'interview', 'knowledge', 'assistant'];
            // 导航激活样式切换
            document.querySelectorAll(".nav-item").forEach((item, index) => {
                item.classList.remove("active");
                if (page === pages[index]) item.classList.add("active");
            });
            // 隐藏所有页面，展示目标页面
            document.querySelectorAll(".page, .chat-page").forEach(el => el.classList.remove("active"));
            document.getElementById(page + "Page").classList.add("active");
            // 切换到面试页时更新岗位难度标题
            if (page === "interview") updateInterviewInfo();
        }

        /**
         * 更新面试页面顶部标题（岗位+难度）
         */
        function updateInterviewInfo() {
            const position = document.getElementById("targetPosition").value.trim() || "未设置岗位";
            const diff = document.getElementById("difficulty").value;
            document.getElementById("interviewInfo").innerText = `${position} · ${diff}难度`;
        }

        // ===================== 简历文件上传解析 =====================
        /**
         * 简历文件选择回调，区分txt直接读取，docx/pdf调用后端解析接口
         */
        async function handleFileUpload() {
            const fileInput = document.getElementById("resumeFile");
            const file = fileInput.files[0]; // 获取选中文件对象
            if (!file) return;

            const filename = file.name.toLowerCase();
            if (!filename.endsWith('.txt') && !filename.endsWith('.docx') && !filename.endsWith('.pdf')) {
                alert("当前不支持该文件类型，请尝试 .txt、.docx 或 .pdf 文件");
                fileInput.value = "";
                uploadedResumeFile = null;
                return;
            }

            uploadedResumeFile = file;
            resetGeneratedResume();
            updateResumeFormatNote();
            // 1、纯文本文件本地读取，不用传给后端
            if (filename.endsWith('.txt')) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    // 读取文本直接填入简历输入框
                    document.getElementById("resumeText").value = e.target.result;
                };
                reader.onerror = function() {
                    alert("文件读取失败，请重试");
                    uploadedResumeFile = null;
                    updateResumeFormatNote();
                };
                reader.readAsText(file, "utf-8");
            }
            // 2、word/pdf 传给后端解析提取文本
            else if (filename.endsWith('.docx') || filename.endsWith('.pdf')) {
                const formData = new FormData();
                formData.append("file", file);
                try {
                    // POST 请求后端上传接口
                    const data = await request("/api/resume/upload", {
                        method: "POST",
                        body: formData   // 请求体直接放FormData二进制，不用手动加headers
                    });
                    if (data.code === 200) {
                        // 后端返回提取好的文本，填充页面文本框
                        document.getElementById("resumeText").value = data.data.content;
                    } else {
                        alert("解析失败：" + data.detail);
                    }
                } catch (e) {
                    uploadedResumeFile = null;
                    fileInput.value = "";
                    updateResumeFormatNote();
                    alert("上传失败：" + e.message);
                }
            }
        }

        function resetGeneratedResume() {
            generatedResumeText = "";
            document.getElementById("fullResumeResult").innerHTML = '<span class="empty-tip">点击上方按钮生成完整简历</span>';
            document.getElementById("exportResumeBtn").disabled = true;
        }

        function updateResumeFormatNote() {
            const note = document.getElementById("resumeFormatNote");
            if (!uploadedResumeFile) {
                note.innerText = "未上传源文件时默认导出 TXT；DOCX 将尽量保留原样式，PDF 会保留文件类型和页面尺寸并重新排版。";
                return;
            }
            const extension = uploadedResumeFile.name.split('.').pop().toUpperCase();
            note.innerText = extension === "PDF"
                ? "将导出 PDF，并沿用源文件页面尺寸；复杂排版、图片和图形无法原样保留。"
                : `将按源文件的 ${extension} 类型导出${extension === "DOCX" ? "，并尽量保留原文档样式与页面设置" : ""}。`;
        }

        // ===================== 知识库上传接口 =====================
        /**
         * 上传txt面经文件到向量库
         */
        async function uploadKnowledge() {
            const fileInput = document.getElementById("knowledgeFile");
            const textInput = document.getElementById("knowledgeText");
            const file = fileInput.files[0];
            const pastedText = textInput.value.trim();

            if (!file && !pastedText) {
                return alert("请粘贴岗位职责或选择 TXT、DOCX、PDF 文件");
            }

            if (file) {
                const filename = file.name.toLowerCase();
                if (![".txt", ".docx", ".pdf"].some(extension => filename.endsWith(extension))) {
                    return alert("仅支持 TXT、DOCX、PDF 文件");
                }
            }

            const btn = document.getElementById("uploadBtn");
            btn.disabled = true;
            btn.innerText = "正在保存...";

            const formData = new FormData();
            if (file) formData.append("file", file);
            if (pastedText) formData.append("content", pastedText);

            try {
                const data = await request("/api/knowledge/upload", {
                    method: "POST",
                    body: formData
                });
                document.getElementById("knowledgeResult").innerText = data.data.message;
                fileInput.value = "";
                textInput.value = "";
            } catch (error) {
                alert("岗位职责保存失败：" + error.message);
            } finally {
                btn.disabled = false;
                btn.innerText = "保存岗位职责";
            }
        }

        // ===================== 通用工具函数 =====================
        /**
         * 获取输入框填写的目标岗位文本
         * @returns {string} 岗位名称
         */
        function getCurrentPosition() {
            return document.getElementById("targetPosition").value.trim();
        }

        function getJobDescription() {
            return document.getElementById("jobDescription").value.trim();
        }

        /**
         * 岗位/难度修改后重置面试会话，清空历史对话
         */
        function onPositionChange() {
            if (interviewSessionId) resetInterview();
            updateInterviewInfo();
        }

        // ===================== 简历优化功能 =====================
        /**
         * 请求后端生成简历优化建议
         */
        async function optimizeResume() {
            const resume = document.getElementById("resumeText").value.trim();
            const position = getCurrentPosition();
            const jobDescription = getJobDescription();

            // 校验必填项
            if (!resume) return alert("请先填写或上传简历");
            if (!position) return alert("请输入目标岗位");

            const btn = document.getElementById("optBtn");
            const resultBox = document.getElementById("optResult");

            btn.disabled = true;
            btn.innerText = "生成中...";
            resultBox.innerHTML = "";

            try {
                const data = await request("/api/resume/optimize", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        resume_text: resume,
                        target_position: position,
                        job_description: jobDescription
                    })
                });
                resultBox.innerText = data.data.suggestion;
            } catch (e) {
                alert("请求失败：" + e.message);
            } finally {
                btn.disabled = false;
                btn.innerText = "生成优化建议";
            }
        }

        /**
         * 请求后端生成完整优化后的简历
         */
        async function generateFullResume() {
            const resume = document.getElementById("resumeText").value.trim();
            const position = getCurrentPosition();
            const jobDescription = getJobDescription();

            if (!resume) return alert("请先填写或上传简历");
            if (!position) return alert("请输入目标岗位");

            const btn = document.getElementById("genBtn");
            const resultBox = document.getElementById("fullResumeResult");

            btn.disabled = true;
            btn.innerText = "生成中...";
            resultBox.innerHTML = "";
            generatedResumeText = "";
            document.getElementById("exportResumeBtn").disabled = true;

            try {
                const data = await request("/api/resume/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        resume_text: resume,
                        target_position: position,
                        job_description: jobDescription
                    })
                });
                generatedResumeText = data.data.resume;
                resultBox.innerText = generatedResumeText;
                document.getElementById("exportResumeBtn").disabled = false;
            } catch (e) {
                alert("生成失败：" + e.message);
            } finally {
                btn.disabled = false;
                btn.innerText = "生成完整简历";
            }
        }

        // ===================== 面试模拟模块 =====================
        /**
         * 重置面试会话，清空聊天记录、销毁会话ID
         */
        function resetInterview() {
            // 关闭流式连接
            if (interviewAbortController) {
                interviewAbortController.abort();
                interviewAbortController = null;
            }
            interviewSessionId = "";
            interviewIsTyping = false;
            interviewCompleted = false;
            currentInterviewReport = null;
            currentInterviewHistoryId = null;
            document.getElementById("interviewSendBtn").disabled = false;
            document.getElementById("interviewVoiceBtn").disabled = false;
            document.getElementById("finishInterviewBtn").disabled = false;
            document.getElementById("finishInterviewBtn").innerText = "结束面试并评分";
            document.getElementById("interviewInput").value = "";
            document.getElementById("interviewInputBar").hidden = false;
            document.getElementById("interviewReport").hidden = true;
            document.getElementById("interviewReport").innerHTML = "";
            document.getElementById("interviewHistoryPanel").hidden = true;
            document.getElementById("interviewHistoryBtn").innerText = "历史记录";
            // 重置聊天框内容
            const chatBox = document.getElementById("interviewChatBox");
            chatBox.hidden = false;
            chatBox.innerHTML = `
                <div class="msg-item assistant">
                    <div class="role-tag">系统</div>
                    <div class="msg-content">对话已重置，请发送第一条消息重新开始面试。</div>
                </div>
            `;
            updateInterviewInfo();
        }

        /**
         * 发送面试回答，初始化会话/流式获取面试官提问
         */
        async function sendInterviewMessage() {
            // 正在输出时禁止重复发送
            if (interviewIsTyping || interviewCompleted) return;
            stopRecording();
            const input = document.getElementById("interviewInput");
            const text = input.value.trim();
            const position = getCurrentPosition();

            if (!text) return;
            if (!position) return alert("请先设置目标岗位");

            // 添加用户消息到聊天框
            appendMsg("interviewChatBox", "user", "我", text);
            input.value = "";
            interviewIsTyping = true;
            document.getElementById("interviewSendBtn").disabled = true;

            // 首次对话：创建面试会话
            if (!interviewSessionId) {
                const resume = document.getElementById("resumeText").value.trim();
                const diff = document.getElementById("difficulty").value;
                const jobDescription = getJobDescription();

                if (!resume) {
                    alert("请先填写或上传简历");
                    interviewIsTyping = false;
                    document.getElementById("interviewSendBtn").disabled = false;
                    return;
                }
                try {
                    const data = await request("/api/interview/start", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            resume_text: resume,
                            target_position: position,
                            difficulty: diff,
                            job_description: jobDescription
                        })
                    });
                    interviewSessionId = data.data.session_id;
                    document.getElementById("finishInterviewBtn").disabled = false;
                    // 建立流式连接获取第一个面试问题
                    streamInterviewQuestion("");
                } catch (e) {
                    alert("开启面试失败：" + e.message);
                    interviewIsTyping = false;
                    document.getElementById("interviewSendBtn").disabled = false;
                }
                return;
            }

            // 非首次：传入回答，流式获取下一题
            streamInterviewQuestion(text);
        }

        /**
         * SSE流式监听面试官问答输出
         * @param {string} answer 用户本次回答内容
         */
        async function streamInterviewQuestion(answer) {
            const msgDom = appendMsg("interviewChatBox", "assistant", "面试官", "");
            const contentDom = msgDom.querySelector(".msg-content");
            const controller = new AbortController();
            interviewAbortController?.abort();
            interviewAbortController = controller;
            contentDom.classList.add("typing-cursor");
            try {
                await streamPost("/api/interview/stream", { session_id: interviewSessionId, answer }, controller, dataText => {
                    if (dataText === "[DONE]") return;
                    const data = JSON.parse(dataText);
                    if (data.error) throw new Error(data.error);
                    if (data.content) {
                        contentDom.innerText += data.content;
                        scrollToBottom("interviewChatBox");
                    }
                });
            } catch (error) {
                if (error.name !== "AbortError") alert("出错：" + error.message);
            } finally {
                if (interviewAbortController === controller) interviewAbortController = null;
                contentDom.classList.remove("typing-cursor");
                interviewIsTyping = false;
                document.getElementById("interviewSendBtn").disabled = interviewCompleted;
            }
        }

        function createReportSection(title, items) {
            if (!Array.isArray(items) || items.length === 0) return null;
            const section = document.createElement("section");
            section.className = "report-section";
            const heading = document.createElement("div");
            heading.className = "report-section-title";
            heading.textContent = title;
            const list = document.createElement("ul");
            list.className = "report-list";
            items.forEach(item => {
                const listItem = document.createElement("li");
                listItem.textContent = item;
                list.appendChild(listItem);
            });
            section.append(heading, list);
            return section;
        }

        function renderInterviewReport(report) {
            currentInterviewReport = report;
            const panel = document.getElementById("interviewReport");
            panel.innerHTML = "";

            const scoreCard = document.createElement("div");
            scoreCard.className = "report-score-card";
            const score = document.createElement("div");
            score.className = "report-score";
            score.textContent = report.overall_score;
            const scoreUnit = document.createElement("small");
            scoreUnit.textContent = " / 100";
            score.appendChild(scoreUnit);
            const summary = document.createElement("div");
            summary.className = "report-summary";
            summary.textContent = `已回答 ${report.answered_questions} 道题\n${report.summary}`;
            scoreCard.append(score, summary);
            panel.appendChild(scoreCard);

            const dimensions = document.createElement("div");
            dimensions.className = "report-dimensions";
            Object.entries(report.dimension_scores || {}).forEach(([name, value]) => {
                const item = document.createElement("div");
                item.className = "report-dimension";
                const label = document.createElement("div");
                label.className = "report-dimension-name";
                label.textContent = name;
                const dimensionScore = document.createElement("div");
                dimensionScore.className = "report-dimension-score";
                dimensionScore.textContent = value;
                item.append(label, dimensionScore);
                dimensions.appendChild(item);
            });
            panel.appendChild(dimensions);

            [
                createReportSection("主要优势", report.strengths),
                createReportSection("需要改进", report.improvements),
            ].filter(Boolean).forEach(section => panel.appendChild(section));

            if (Array.isArray(report.question_feedback) && report.question_feedback.length) {
                const section = document.createElement("section");
                section.className = "report-section";
                const heading = document.createElement("div");
                heading.className = "report-section-title";
                heading.textContent = "逐题评分";
                section.appendChild(heading);
                report.question_feedback.forEach((feedback, index) => {
                    const card = document.createElement("div");
                    card.className = "question-feedback-card";
                    const title = document.createElement("div");
                    title.className = "question-feedback-title";
                    title.textContent = `第 ${index + 1} 题：${feedback.question}`;
                    const questionScore = document.createElement("div");
                    questionScore.className = "question-feedback-score";
                    questionScore.textContent = `得分：${feedback.score} / 100`;
                    const answer = document.createElement("div");
                    answer.className = "question-feedback-text";
                    answer.textContent = `你的回答：${feedback.answer}`;
                    const review = document.createElement("div");
                    review.className = "question-feedback-text";
                    review.textContent = `评价：${feedback.feedback}`;
                    const betterAnswer = document.createElement("div");
                    betterAnswer.className = "question-feedback-text";
                    betterAnswer.textContent = `改进方向：${feedback.better_answer}`;
                    card.append(title, questionScore, answer, review, betterAnswer);
                    section.appendChild(card);
                });
                panel.appendChild(section);
            }

            const nextSteps = createReportSection("下一步行动", report.next_steps);
            if (nextSteps) panel.appendChild(nextSteps);

            document.getElementById("interviewChatBox").hidden = true;
            document.getElementById("interviewInputBar").hidden = true;
            document.getElementById("interviewHistoryPanel").hidden = true;
            panel.hidden = false;
            document.getElementById("interviewInfo").innerText = `面试完成 · ${report.overall_score} 分`;
        }

        async function finishInterview() {
            if (!interviewSessionId) return alert("请先开始面试");
            if (interviewIsTyping) return alert("请等待当前问题生成完成");

            const btn = document.getElementById("finishInterviewBtn");
            interviewIsTyping = true;
            btn.disabled = true;
            btn.innerText = "评分中...";
            document.getElementById("interviewSendBtn").disabled = true;
            document.getElementById("interviewVoiceBtn").disabled = true;
            try {
                const data = await request("/api/interview/report", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: interviewSessionId })
                });
                interviewCompleted = true;
                renderInterviewReport(data.data.report);
            } catch (error) {
                alert("生成报告失败：" + error.message);
            } finally {
                interviewIsTyping = false;
                btn.disabled = interviewCompleted;
                btn.innerText = interviewCompleted ? "评分已完成" : "结束面试并评分";
                document.getElementById("interviewSendBtn").disabled = interviewCompleted;
                document.getElementById("interviewVoiceBtn").disabled = interviewCompleted;
            }
        }

        function formatHistoryDate(value) {
            if (!value) return "时间未知";
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
        }

        function renderInterviewHistory(items) {
            const panel = document.getElementById("interviewHistoryPanel");
            panel.innerHTML = "";
            const toolbar = document.createElement("div");
            toolbar.className = "history-toolbar";
            const title = document.createElement("div");
            title.className = "history-title";
            title.textContent = "面试历史记录";
            const clearButton = document.createElement("button");
            clearButton.className = "btn btn-reset btn-compact";
            clearButton.textContent = "清空全部";
            clearButton.disabled = !items.length;
            clearButton.addEventListener("click", deleteAllInterviewHistory);
            toolbar.append(title, clearButton);
            panel.appendChild(toolbar);

            if (!items.length) {
                const empty = document.createElement("div");
                empty.className = "history-empty";
                empty.textContent = "暂无已完成的面试报告。完成一次面试并评分后，报告会自动保存到这里。";
                panel.appendChild(empty);
                return;
            }

            items.forEach(item => {
                const row = document.createElement("div");
                row.className = "history-item";
                const main = document.createElement("div");
                main.className = "history-item-main";
                const itemTitle = document.createElement("div");
                itemTitle.className = "history-item-title";
                itemTitle.textContent = `${item.target_position} · ${item.difficulty}`;
                const meta = document.createElement("div");
                meta.className = "history-item-meta";
                meta.textContent = `${formatHistoryDate(item.created_at)} · 已回答 ${item.answered_questions} 道题`;
                main.append(itemTitle, meta);
                const score = document.createElement("div");
                score.className = "history-item-score";
                score.textContent = `${item.overall_score} 分`;
                const actions = document.createElement("div");
                actions.className = "history-item-actions";
                const viewButton = document.createElement("button");
                viewButton.className = "btn";
                viewButton.textContent = "查看报告";
                viewButton.addEventListener("click", () => viewInterviewHistory(item.id, item.session_id));
                const deleteButton = document.createElement("button");
                deleteButton.className = "btn btn-reset";
                deleteButton.textContent = "删除";
                deleteButton.addEventListener("click", () => deleteInterviewHistory(item.id));
                actions.append(viewButton, deleteButton);
                row.append(main, score, actions);
                panel.appendChild(row);
            });
        }

        async function loadInterviewHistory() {
            const panel = document.getElementById("interviewHistoryPanel");
            panel.hidden = false;
            panel.innerHTML = '<div class="history-empty">正在加载历史记录...</div>';
            try {
                const data = await request("/api/interview/history");
                renderInterviewHistory(data.data.items || []);
                document.getElementById("interviewChatBox").hidden = true;
                document.getElementById("interviewInputBar").hidden = true;
                document.getElementById("interviewReport").hidden = true;
                document.getElementById("interviewHistoryBtn").innerText = "返回面试";
                document.getElementById("interviewInfo").innerText = "面试历史记录";
            } catch (error) {
                panel.innerHTML = "";
                const errorMessage = document.createElement("div");
                errorMessage.className = "history-empty";
                errorMessage.textContent = error.message;
                panel.appendChild(errorMessage);
            }
        }

        async function viewInterviewHistory(historyId, sessionId) {
            try {
                const data = await request(`/api/interview/history/${historyId}`);
                interviewSessionId = sessionId || "";
                currentInterviewHistoryId = historyId;
                interviewCompleted = true;
                renderInterviewReport(data.data.report);
                document.getElementById("finishInterviewBtn").disabled = true;
                document.getElementById("finishInterviewBtn").innerText = "评分已完成";
            } catch (error) {
                alert("历史报告加载失败：" + error.message);
            }
        }

        async function deleteInterviewHistory(historyId) {
            if (!window.confirm("删除后将同时清理该面试的问答和评分报告，确定继续吗？")) return;
            try {
                await request(`/api/interview/history/${historyId}`, { method: "DELETE" });
                if (currentInterviewHistoryId === historyId) {
                    resetInterview();
                }
                await loadInterviewHistory();
            } catch (error) {
                alert("删除失败：" + error.message);
            }
        }

        async function deleteAllInterviewHistory() {
            if (!window.confirm("将删除当前账号的全部面试历史和评分报告，确定继续吗？")) return;
            try {
                await request("/api/interview/history", { method: "DELETE" });
                resetInterview();
                await loadInterviewHistory();
            } catch (error) {
                alert("清空失败：" + error.message);
            }
        }

        function toggleInterviewHistory() {
            const panel = document.getElementById("interviewHistoryPanel");
            if (!panel.hidden) {
                panel.hidden = true;
                document.getElementById("interviewHistoryBtn").innerText = "历史记录";
                if (currentInterviewReport) {
                    document.getElementById("interviewReport").hidden = false;
                    document.getElementById("interviewInfo").innerText = `面试完成 · ${currentInterviewReport.overall_score} 分`;
                } else {
                    document.getElementById("interviewChatBox").hidden = false;
                    document.getElementById("interviewInputBar").hidden = false;
                    updateInterviewInfo();
                }
                return;
            }
            loadInterviewHistory();
        }

        function getDownloadFilename(response) {
            const disposition = response.headers.get("Content-Disposition") || "";
            const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
            if (encodedMatch) return decodeURIComponent(encodedMatch[1]);
            const basicMatch = disposition.match(/filename="?([^";]+)"?/i);
            return basicMatch ? basicMatch[1] : "优化后简历.txt";
        }

        async function exportResume() {
            if (!generatedResumeText) return alert("请先生成完整简历");

            const btn = document.getElementById("exportResumeBtn");
            const formData = new FormData();
            formData.append("optimized_text", generatedResumeText);
            if (uploadedResumeFile) formData.append("file", uploadedResumeFile);

            btn.disabled = true;
            btn.innerText = "导出中...";
            try {
                const response = await fetch(`${BACKEND}/api/resume/export`, {
                    method: "POST",
                    credentials: "include",
                    body: formData
                });
                if (response.status === 401) {
                    showAuthOverlay();
                    throw new Error("登录状态已失效，请重新登录");
                }
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `导出失败 ${response.status}`);
                }

                const blob = await response.blob();
                const downloadUrl = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = downloadUrl;
                link.download = getDownloadFilename(response);
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(downloadUrl);
            } catch (e) {
                alert("导出失败：" + e.message);
            } finally {
                btn.disabled = false;
                btn.innerText = "导出优化后简历";
            }
        }

        // ===================== AI助手通用问答模块 =====================
        /**
         * 清空AI助手对话，重置会话
         */
        function resetAssistant() {
            if (assistantAbortController) {
                assistantAbortController.abort();
                assistantAbortController = null;
            }
            chatSessionId = "";
            chatIsTyping = false;
            document.getElementById("assistantSendBtn").disabled = false;
            const chatBox = document.getElementById("assistantChatBox");
            chatBox.innerHTML = `
                <div class="msg-item assistant">
                    <div class="role-tag">AI助手</div>
                    <div class="msg-content">对话已清空，你可以重新开始提问。</div>
                </div>
            `;
        }

        /**
         * 发送用户问题，初始化会话并流式获取AI回复
         */
        async function sendAssistantMessage() {
            if (chatIsTyping) return;
            const input = document.getElementById("assistantInput");
            const text = input.value.trim();

            if (!text) return;
            appendMsg("assistantChatBox", "user", "我", text);
            input.value = "";
            chatIsTyping = true;
            document.getElementById("assistantSendBtn").disabled = true;

            // 首次对话创建会话
            if (!chatSessionId) {
                try {
                    const data = await request("/api/chat/start", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" }
                    });
                    chatSessionId = data.data.session_id;
                    streamChatReply(text);
                } catch (e) {
                    alert("开启会话失败：" + e.message);
                    chatIsTyping = false;
                    document.getElementById("assistantSendBtn").disabled = false;
                }
                return;
            }

            // 已有会话直接流式提问
            streamChatReply(text);
        }

        /**
         * AI助手SSE流式输出回复
         * @param {string} message 用户提问文本
         */
        async function streamChatReply(message) {
            const msgDom = appendMsg("assistantChatBox", "assistant", "AI助手", "");
            const contentDom = msgDom.querySelector(".msg-content");
            const controller = new AbortController();
            assistantAbortController?.abort();
            assistantAbortController = controller;
            contentDom.classList.add("typing-cursor");
            try {
                await streamPost("/api/chat/stream", { session_id: chatSessionId, message }, controller, dataText => {
                    if (dataText === "[DONE]") return;
                    const data = JSON.parse(dataText);
                    if (data.error) throw new Error(data.error);
                    if (data.content) {
                        contentDom.innerText += data.content;
                        scrollToBottom("assistantChatBox");
                    }
                });
            } catch (error) {
                if (error.name !== "AbortError") alert("出错：" + error.message);
            } finally {
                if (assistantAbortController === controller) assistantAbortController = null;
                contentDom.classList.remove("typing-cursor");
                chatIsTyping = false;
                document.getElementById("assistantSendBtn").disabled = false;
            }
        }

        // ===================== 聊天框通用工具 =====================
        /**
         * 向聊天框追加一条消息DOM
         * @param {string} boxId 聊天容器id
         * @param {string} role user/assistant 消息角色
         * @param {string} tag 角色展示文字
         * @param {string} content 消息内容
         * @returns {HTMLElement} 新建消息dom节点
         */
        function appendMsg(boxId, role, tag, content) {
            const chatBox = document.getElementById(boxId);
            const div = document.createElement("div");
            div.className = `msg-item ${role}`;
            div.innerHTML = `
                <div class="role-tag">${tag}</div>
                <div class="msg-content">${content}</div>
            `;
            chatBox.appendChild(div);
            scrollToBottom(boxId);
            return div;
        }

        /**
         * 聊天框自动滚动到底部
         * @param {string} boxId 聊天容器id
         */
        function scrollToBottom(boxId) {
            const chatBox = document.getElementById(boxId);
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        document.getElementById("authForm").addEventListener("submit", submitAuth);
        initSpeechRecognition();
        loadCurrentUser();
        document.getElementById("authSwitchBtn").addEventListener("click", toggleAuthMode);
        document.querySelectorAll(".nav-item[data-page]").forEach((item) => {
            item.addEventListener("click", () => switchPage(item.dataset.page));
        });
        document.getElementById("logoutBtn").addEventListener("click", logout);
        document.getElementById("resumeFile").addEventListener("click", (event) => {
            event.currentTarget.value = "";
        });
        document.getElementById("resumeFile").addEventListener("change", handleFileUpload);
        document.getElementById("targetPosition").addEventListener("change", onPositionChange);
        document.getElementById("jobDescription").addEventListener("change", onPositionChange);
        document.getElementById("difficulty").addEventListener("change", onPositionChange);
        document.getElementById("optBtn").addEventListener("click", optimizeResume);
        document.getElementById("genBtn").addEventListener("click", generateFullResume);
        document.getElementById("exportResumeBtn").addEventListener("click", exportResume);
        document.getElementById("finishInterviewBtn").addEventListener("click", finishInterview);
        document.getElementById("interviewHistoryBtn").addEventListener("click", toggleInterviewHistory);
        document.getElementById("resetInterviewBtn").addEventListener("click", resetInterview);
        document.getElementById("interviewVoiceBtn").addEventListener("click", toggleInterviewVoice);
        document.getElementById("interviewSendBtn").addEventListener("click", sendInterviewMessage);
        document.getElementById("uploadBtn").addEventListener("click", uploadKnowledge);
        document.getElementById("resetAssistantBtn").addEventListener("click", resetAssistant);
        document.getElementById("assistantSendBtn").addEventListener("click", sendAssistantMessage);
        document.getElementById("interviewInput").addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                sendInterviewMessage();
            }
        });
        document.getElementById("assistantInput").addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                sendAssistantMessage();
            }
        });

        const requestedPage = new URLSearchParams(window.location.search).get("page");
        if (["resume", "interview", "knowledge", "assistant"].includes(requestedPage)) {
            switchPage(requestedPage);
        }
