/* api.js — 后端 API 封装 */

// Auth
async function apiRegister(username, password, coupleCode) {
    const res = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, couple_code: coupleCode || null }),
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '注册失败');
    }
    return res.json();
}

async function apiLogin(username, password) {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '登录失败');
    }
    return res.json();
}

// Moments
async function apiGetMoments() {
    const res = await fetch(`${API_BASE}/api/moments`, {
        headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error('获取瞬间失败');
    return res.json();
}

async function apiCreateMoment(data) {
    const res = await fetch(`${API_BASE}/api/moments`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
        },
        body: JSON.stringify(data),
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '发布失败');
    }
    return res.json();
}

async function apiDeleteMoment(id) {
    const res = await fetch(`${API_BASE}/api/moments/${id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error('删除失败');
    return res.json();
}

async function apiUploadImage(file, momentId) {
    const formData = new FormData();
    formData.append('file', file);
    if (momentId) formData.append('moment_id', momentId);

    const res = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${getToken()}` },
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '上传失败');
    }
    return res.json();
}

// Anniversaries
async function apiGetAnniversaries() {
    const res = await fetch(`${API_BASE}/api/anniversaries`, {
        headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error('获取纪念日失败');
    return res.json();
}

async function apiCreateAnniversary(data) {
    const res = await fetch(`${API_BASE}/api/anniversaries`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
        },
        body: JSON.stringify(data),
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '保存失败');
    }
    return res.json();
}
