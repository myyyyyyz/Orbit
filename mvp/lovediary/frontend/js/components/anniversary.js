/* anniversary.js — 纪念日组件 */

function initAnniversary() {
    const openBtn = document.getElementById('openAnniversaryBtn');
    const formContainer = document.getElementById('anniversaryFormContainer');
    const cancelBtn = document.getElementById('cancelAnniversaryBtn');
    const form = document.getElementById('anniversaryForm');

    openBtn.addEventListener('click', () => {
        formContainer.style.display = 'block';
        openBtn.style.display = 'none';
    });

    cancelBtn.addEventListener('click', () => {
        formContainer.style.display = 'none';
        openBtn.style.display = '';
        form.reset();
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('anniversaryName').value.trim();
        const date = document.getElementById('anniversaryDate').value;
        const type = document.getElementById('anniversaryType').value;

        if (!name || !date) {
            alert('请填写名称和日期');
            return;
        }

        try {
            await apiCreateAnniversary({ name, date, type });
            form.reset();
            formContainer.style.display = 'none';
            openBtn.style.display = '';
            loadAnniversaries();
        } catch (err) {
            alert('保存失败：' + err.message);
        }
    });
}

async function loadAnniversaries() {
    const container = document.getElementById('anniversaryList');
    try {
        const data = await apiGetAnniversaries();
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="empty-state">还没有纪念日，添加一个吧</div>';
            return;
        }

        const typeMap = {
            love_start: '💕',
            first_date: '🌟',
            proposal: '💍',
            wedding: '🎊',
            custom: '💝',
        };

        container.innerHTML = data.map(a => {
            const icon = typeMap[a.type] || '💝';
            return `
                <div class="anniversary-item">
                    <div class="days-badge">${a.days_until === 0 ? '🎉' : a.days_until}</div>
                    <div class="days-label">${a.days_until === 0 ? '就是今天！' : '天后'}</div>
                    <div class="anni-name">${icon} ${escapeHtml(a.name)}</div>
                    <div class="anni-date">${a.days_since}天前开始</div>
                </div>
            `;
        }).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-state">加载纪念日失败</div>';
    }
}
