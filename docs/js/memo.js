// docs/js/memo.js
// 메모 탭: GitHubAPI(Pattern A) + 포트폴리오/SPY 차트 + 코멘트 CRUD

class GitHubAPI {
    constructor(token) {
        this.token = token;
        this.owner = 'Junghyun99';
        this.repo = 'StockAsset';
        this.baseUrl = `https://api.github.com/repos/${this.owner}/${this.repo}`;
    }

    get _headers() {
        return {
            'Authorization': `Bearer ${this.token}`,
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        };
    }

    async getFile(path) {
        const res = await fetch(`${this.baseUrl}/contents/${path}?t=${Date.now()}`, {
            headers: this._headers
        });
        if (res.status === 404) return { content: '[]', sha: null };
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(`[${res.status}] ${e.message || res.statusText}`);
        }
        const data = await res.json();
        const content = decodeURIComponent(escape(atob(data.content.replace(/\n/g, ''))));
        return { content, sha: data.sha };
    }

    async updateFile(path, content, message, sha) {
        const encoded = btoa(unescape(encodeURIComponent(content)));
        const body = { message, content: encoded };
        if (sha) body.sha = sha;
        const res = await fetch(`${this.baseUrl}/contents/${path}`, {
            method: 'PUT',
            headers: this._headers,
            body: JSON.stringify(body)
        });
        if (res.status === 409) throw new Error('충돌: 파일이 그 사이 변경됨. 다시 시도하세요.');
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(`저장 실패: ${e.message || res.statusText}`);
        }
        const data = await res.json();
        return data.content.sha;
    }
}

class MemoTab {
    constructor(summaryData, accountId) {
        this.summaryData = summaryData;
        this.accountId = accountId || 'default';
        this.filePath = `docs/data/${this.accountId}/comment.json`;
        this.comments = [];
        this.currentSha = null;
        this.githubApi = null;
        this.chart = null;
        this._commentLabelIndices = {};
        this._token = localStorage.getItem('memoGithubToken') || '';
    }

    async init() {
        this._setupAuthUI();
        await this._loadComments();
        this._renderChart();
        this._renderCommentList();
        this._setupAddForm();
    }

    _setupAuthUI() {
        const tokenInput = document.getElementById('memo-github-token');
        const saveBtn = document.getElementById('memo-token-save');
        const statusEl = document.getElementById('memo-token-status');
        if (!tokenInput || !saveBtn || !statusEl) return;

        tokenInput.value = this._token;
        if (this._token) {
            this.githubApi = new GitHubAPI(this._token);
            statusEl.innerHTML = '<span class="text-success"><i class="fas fa-check-circle"></i> 토큰 저장됨</span>';
        }

        saveBtn.addEventListener('click', () => {
            const t = tokenInput.value.trim();
            if (!t) {
                statusEl.innerHTML = '<span class="text-danger">토큰을 입력하세요.</span>';
                return;
            }
            this._token = t;
            localStorage.setItem('memoGithubToken', t);
            this.githubApi = new GitHubAPI(t);
            statusEl.innerHTML = '<span class="text-success"><i class="fas fa-check-circle"></i> 저장됨</span>';
            this._updateFormState();
        });
    }

    async _loadComments() {
        try {
            const res = await fetch(`data/${this.accountId}/comment.json?t=${Date.now()}`);
            this.comments = res.ok ? await res.json() : [];
        } catch {
            this.comments = [];
        }
        // sha는 저장 시점에 getFile()로 최신 값 취득하므로 여기서는 생략
    }

    _renderChart() {
        const canvas = document.getElementById('memoChart');
        if (!canvas) return;
        if (this.chart) { this.chart.destroy(); this.chart = null; }

        const data = this.summaryData;
        if (!data || data.length === 0) return;

        const labels = data.map(d => d.date);
        const firstValue = data[0]?.total_value || 0;
        const firstSpy = data[0]?.spy_price || 0;

        const portfolioReturns = data.map(d => firstValue ? ((d.total_value / firstValue) - 1) * 100 : 0);
        const spyReturns = data.map(d => firstSpy ? ((d.spy_price / firstSpy) - 1) * 100 : 0);

        // 코멘트 마커 어노테이션 생성
        this._commentLabelIndices = {};
        const annotations = {};
        this.comments.forEach((c, i) => {
            const nearestDate = this._findNearestDate(labels, c.date);
            if (!nearestDate) return;
            this._commentLabelIndices[i] = labels.indexOf(nearestDate);
            annotations[`comment_${i}`] = {
                type: 'line',
                xMin: nearestDate,
                xMax: nearestDate,
                borderColor: 'rgba(255, 193, 7, 0.9)',
                borderWidth: 2,
                borderDash: [5, 3],
                drawTime: 'afterDraw'
            };
        });

        this.chart = new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: '포트폴리오 수익률 (%)',
                        data: portfolioReturns,
                        borderColor: '#0d6efd',
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: 'SPY 수익률 (%)',
                        data: spyReturns,
                        borderColor: 'rgba(253, 126, 20, 0.85)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                onClick: (evt, _elements, chart) => this._onChartClick(evt, chart),
                scales: {
                    x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } },
                    y: {
                        title: { display: true, text: '수익률 (%)' },
                        ticks: { callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%' }
                    }
                },
                plugins: {
                    annotation: { annotations },
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            padding: 20,
                            generateLabels: chart => {
                                const labels = Chart.defaults.plugins.legend.labels.generateLabels(chart);
                                if (Object.keys(annotations).length > 0) {
                                    labels.push({
                                        text: '코멘트 (클릭)',
                                        strokeStyle: 'rgba(255, 193, 7, 0.9)',
                                        fillStyle: 'rgba(255, 193, 7, 0.3)',
                                        lineWidth: 2,
                                        pointStyle: 'line',
                                        hidden: false
                                    });
                                }
                                return labels;
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const v = ctx.parsed.y;
                                return `${ctx.dataset.label}: ${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
                            },
                            afterBody: ctx => {
                                const labelIndex = ctx[0]?.dataIndex;
                                if (labelIndex == null) return [];
                                const matched = Object.entries(this._commentLabelIndices)
                                    .filter(([, li]) => li === labelIndex)
                                    .map(([ci]) => this.comments[parseInt(ci)])
                                    .filter(Boolean);
                                if (matched.length === 0) return [];
                                return ['─────────────', ...matched.map(c => `📝 ${c.text.split('\n')[0].slice(0, 40)}`)];
                            }
                        }
                    }
                }
            }
        });
    }

    _findNearestDate(labels, targetDate) {
        if (labels.includes(targetDate)) return targetDate;
        const targetMs = new Date(targetDate).getTime();
        let nearest = null;
        let minDiff = Infinity;
        labels.forEach(l => {
            const diff = Math.abs(new Date(l).getTime() - targetMs);
            if (diff < minDiff) { minDiff = diff; nearest = l; }
        });
        return nearest;
    }

    _onChartClick(evt, chart) {
        const xScale = chart.scales.x;
        if (!xScale || evt.x == null) return;

        const raw = xScale.getValueForPixel(evt.x);
        const labelIndex = Math.round(raw);
        if (labelIndex < 0 || labelIndex >= chart.data.labels.length) return;

        const matched = Object.entries(this._commentLabelIndices)
            .filter(([, li]) => Math.abs(li - labelIndex) <= 1)
            .map(([ci]) => this.comments[parseInt(ci)])
            .filter(Boolean);

        if (matched.length === 0) return;
        this._showCommentPopover(matched, evt);
    }

    _showCommentPopover(comments, evt) {
        document.getElementById('memo-comment-popup')?.remove();

        const popup = document.createElement('div');
        popup.id = 'memo-comment-popup';
        popup.className = 'card border shadow-lg';
        const nativeEvt = evt.native || evt;
        const clientX = nativeEvt.clientX ?? 0;
        const clientY = nativeEvt.clientY ?? 0;
        popup.style.cssText = [
            'position: fixed',
            'z-index: 9999',
            'max-width: 320px',
            'min-width: 200px',
            `top: ${Math.min(clientY + 12, window.innerHeight - 220)}px`,
            `left: ${Math.min(clientX + 12, window.innerWidth - 340)}px`
        ].join(';');

        popup.innerHTML = `
            <div class="card-header py-2 d-flex justify-content-between align-items-center" style="background:rgba(255,193,7,0.2)">
                <span class="fw-bold small">📝 메모</span>
                <button type="button" class="btn-close" style="width:.6rem;height:.6rem;font-size:.6rem"></button>
            </div>
            <div class="card-body py-2 px-3">
                ${comments.map((c, i) => `
                    ${i > 0 ? '<hr class="my-2">' : ''}
                    <div class="text-muted small mb-1">${c.date}</div>
                    <div class="small" style="white-space:pre-wrap">${this._escapeHtml(c.text)}</div>
                `).join('')}
            </div>
        `;

        popup.querySelector('.btn-close').addEventListener('click', () => popup.remove());
        document.body.appendChild(popup);

        setTimeout(() => {
            const handler = e => {
                if (!popup.contains(e.target)) {
                    popup.remove();
                    document.removeEventListener('click', handler);
                }
            };
            document.addEventListener('click', handler);
        }, 150);
    }

    _escapeHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    _renderCommentList() {
        const listEl = document.getElementById('memo-comment-list');
        if (!listEl) return;

        if (this.comments.length === 0) {
            listEl.innerHTML = '<p class="text-muted text-center py-3 mb-0">코멘트가 없습니다.</p>';
            return;
        }

        // 날짜 역순 정렬 (원본 인덱스 보존)
        const sorted = this.comments
            .map((c, i) => ({ ...c, _origIdx: i }))
            .sort((a, b) => b.date.localeCompare(a.date));

        const hasToken = !!this.githubApi;
        listEl.innerHTML = sorted.map(c => `
            <div class="card border-0 bg-light mb-2">
                <div class="card-body py-2 px-3">
                    <div class="d-flex justify-content-between align-items-start mb-1">
                        <span class="badge bg-warning text-dark">${c.date}</span>
                        <button class="btn btn-sm btn-outline-danger border-0 py-0 memo-delete-btn"
                                data-index="${c._origIdx}" ${hasToken ? '' : 'disabled'}>
                            <i class="fas fa-trash-alt" style="font-size:.7rem"></i>
                        </button>
                    </div>
                    <p class="mb-0 small" style="white-space:pre-wrap">${this._escapeHtml(c.text)}</p>
                </div>
            </div>
        `).join('');

        listEl.querySelectorAll('.memo-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.index, 10);
                this._handleDelete(idx);
            });
        });
    }

    _setupAddForm() {
        const form = document.getElementById('memo-add-form');
        const dateInput = document.getElementById('memo-date');
        const textInput = document.getElementById('memo-text');
        const submitBtn = document.getElementById('memo-submit');
        const feedbackEl = document.getElementById('memo-feedback');
        if (!form || !dateInput || !textInput || !submitBtn || !feedbackEl) return;

        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        dateInput.value = `${yyyy}-${mm}-${dd}`;
        this._updateFormState();

        form.addEventListener('submit', async e => {
            e.preventDefault();
            const date = dateInput.value.trim();
            const text = textInput.value.trim();
            if (!date || !text) return;
            if (!this.githubApi) {
                feedbackEl.innerHTML = '<span class="text-danger">GitHub 토큰을 먼저 입력하세요.</span>';
                return;
            }

            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>저장 중...';
            feedbackEl.innerHTML = '';

            try {
                await this._handleAdd(date, text);
                textInput.value = '';
                feedbackEl.innerHTML = '<span class="text-success"><i class="fas fa-check me-1"></i>저장되었습니다.</span>';
            } catch (err) {
                feedbackEl.innerHTML = `<span class="text-danger"><i class="fas fa-times me-1"></i>${err.message}</span>`;
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-save me-1"></i>저장하기';
            }
        });
    }

    _updateFormState() {
        const submitBtn = document.getElementById('memo-submit');
        if (submitBtn) submitBtn.disabled = !this.githubApi;
        document.querySelectorAll('.memo-delete-btn').forEach(btn => {
            btn.disabled = !this.githubApi;
        });
    }

    async _handleAdd(date, text) {
        const newComment = { date, text, created_at: new Date().toISOString() };
        this.comments.push(newComment);
        try {
            await this._saveToGitHub();
            this._renderChart();
            this._renderCommentList();
        } catch (err) {
            this.comments.pop();
            throw err;
        }
    }

    async _handleDelete(index) {
        if (!this.githubApi) return;
        if (!confirm('코멘트를 삭제하시겠습니까?')) return;
        const removed = this.comments.splice(index, 1)[0];
        try {
            await this._saveToGitHub();
            this._renderChart();
            this._renderCommentList();
        } catch (err) {
            if (removed) this.comments.splice(index, 0, removed);
            alert(`삭제 실패: ${err.message}`);
        }
    }

    async _saveToGitHub() {
        if (!this.githubApi) throw new Error('GitHub 토큰이 없습니다.');
        // 항상 최신 sha를 가져와 충돌 방지
        const { sha } = await this.githubApi.getFile(this.filePath);
        const content = JSON.stringify(this.comments, null, 2);
        const msg = `memo: update comments for ${this.accountId}`;
        this.currentSha = await this.githubApi.updateFile(this.filePath, content, msg, sha);
    }
}

export function initMemoTab(summaryData, accountId) {
    const tab = new MemoTab(summaryData, accountId);
    tab.init().catch(err => console.error('[MemoTab]', err));
}
