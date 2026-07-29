/* timeline.js — 时间线组件 */

async function loadTimeline() {
    const container = document.getElementById('timelineList');
    const loading = document.getElementById('loadingState');
    const empty = document.getElementById('emptyState');
    const error = document.getElementById('errorState');

    // Show loading
    show(loading);
    hide(empty);
    hide(error);
    hide(container);

    try {
        const data = await apiGetMoments();

        if (!data || data.length === 0) {
            hide(loading);
            show(empty);
            return;
        }

        container.innerHTML = data.map((m, index) => {
            const tagsHtml = (m.tags && m.tags.length > 0)
                ? `<div class="moment-tags">${m.tags.map(t => `<span class="moment-tag">#${escapeHtml(t)}</span>`).join('')}</div>`
                : '';

            const imageHtml = m.image_url
                ? `<img src="${API_BASE}${m.image_url}" alt="${escapeHtml(m.title)}" class="moment-image" loading="lazy">`
                : '';

            const locationHtml = m.location_name
                ? `<div class="moment-location">📍 ${escapeHtml(m.location_name)}</div>`
                : (m.latitude ? `<div class="moment-location">📍 ${m.latitude.toFixed(4)}, ${m.longitude.toFixed(4)}</div>` : '');

            return `
                <div class="timeline-item" style="animation-delay: ${index * 0.08}s">
                    <div class="card">
                        <div class="moment-header">
                            <span class="moment-title">${escapeHtml(m.title)}</span>
                            <span class="moment-date">${formatDate(m.date)}</span>
                        </div>
                        ${m.content ? `<div class="moment-content">${escapeHtml(m.content)}</div>` : ''}
                        ${imageHtml}
                        ${tagsHtml}
                        ${locationHtml}
                        <div class="moment-actions">
                            <button class="btn btn-sm btn-ghost" onclick="deleteMoment(${m.id})" title="删除">
                                🗑️
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        hide(loading);
        hide(empty);
        show(container);
    } catch (err) {
        hide(loading);
        hide(empty);
        show(error);
    }
}

async function deleteMoment(id) {
    if (!confirm('确定删除这条瞬间吗？')) return;
    try {
        await apiDeleteMoment(id);
        loadTimeline();
    } catch (err) {
        alert('删除失败：' + err.message);
    }
}
