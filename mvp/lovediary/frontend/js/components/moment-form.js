/* moment-form.js — 发布瞬间组件 */

function initMomentForm() {
    const openBtn = document.getElementById('openPostBtn');
    const formContainer = document.getElementById('postFormContainer');
    const cancelBtn = document.getElementById('cancelPostBtn');
    const form = document.getElementById('momentForm');
    const getLocationBtn = document.getElementById('getLocationBtn');

    openBtn.addEventListener('click', () => {
        formContainer.style.display = 'block';
        openBtn.style.display = 'none';
    });

    cancelBtn.addEventListener('click', () => {
        formContainer.style.display = 'none';
        openBtn.style.display = '';
        form.reset();
        hideLocationInfo();
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const title = document.getElementById('momentTitle').value.trim();
        const content = document.getElementById('momentContent').value.trim();
        const date = document.getElementById('momentDate').value;
        const tagsStr = document.getElementById('momentTags').value.trim();
        const imageFile = document.getElementById('momentImage').files[0];
        const lat = document.getElementById('momentLat').value;
        const lng = document.getElementById('momentLng').value;
        const locName = document.getElementById('momentLocName').value;

        if (!title || !date) {
            alert('请填写标题和日期');
            return;
        }

        try {
            const data = {
                title,
                content: content || null,
                date,
                tags: tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [],
                latitude: lat ? parseFloat(lat) : null,
                longitude: lng ? parseFloat(lng) : null,
                location_name: locName || null,
            };

            const moment = await apiCreateMoment(data);

            // Upload image if selected
            if (imageFile) {
                await apiUploadImage(imageFile, moment.id);
            }

            form.reset();
            hideLocationInfo();
            formContainer.style.display = 'none';
            openBtn.style.display = '';
            loadTimeline();
        } catch (err) {
            alert('发布失败：' + err.message);
        }
    });

    // Location
    getLocationBtn.addEventListener('click', () => {
        if (!navigator.geolocation) {
            alert('浏览器不支持定位');
            return;
        }
        getLocationBtn.textContent = '📍 获取中...';
        getLocationBtn.disabled = true;
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                document.getElementById('momentLat').value = pos.coords.latitude;
                document.getElementById('momentLng').value = pos.coords.longitude;
                document.getElementById('momentLocName').value =
                    `${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;

                const locInfo = document.getElementById('locationInfo');
                locInfo.textContent = `📍 已获取位置: ${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
                locInfo.style.display = 'block';

                getLocationBtn.textContent = '📍 获取位置';
                getLocationBtn.disabled = false;
            },
            (err) => {
                alert('获取位置失败: ' + err.message);
                getLocationBtn.textContent = '📍 获取位置';
                getLocationBtn.disabled = false;
            }
        );
    });
}

function hideLocationInfo() {
    document.getElementById('locationInfo').style.display = 'none';
    document.getElementById('momentLat').value = '';
    document.getElementById('momentLng').value = '';
    document.getElementById('momentLocName').value = '';
}
