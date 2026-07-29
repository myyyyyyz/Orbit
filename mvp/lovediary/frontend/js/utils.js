/* utils.js — 工具函数 */

const API_BASE = 'http://localhost:8000';

function getToken() {
    return localStorage.getItem('lovediary_token');
}

function setToken(token) {
    localStorage.setItem('lovediary_token', token);
}

function clearToken() {
    localStorage.removeItem('lovediary_token');
}

function getAuthHeaders() {
    const token = getToken();
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr.replace(/-/g, '/'));
    const year = d.getFullYear();
    const month = d.getMonth() + 1;
    const day = d.getDate();
    const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    const weekday = weekdays[d.getDay()];
    return `${year}年${month}月${day}日 星期${weekday}`;
}

function timeAgo(dateStr) {
    const now = new Date();
    const past = new Date(dateStr);
    const diff = Math.floor((now - past) / 1000);

    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`;
    return formatDate(dateStr.split('T')[0]);
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function show(el) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (el) el.style.display = '';
}

function hide(el) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (el) el.style.display = 'none';
}

function toggle(el) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}
