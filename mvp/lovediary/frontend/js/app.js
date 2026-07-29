/* app.js — 主应用逻辑 */

document.addEventListener('DOMContentLoaded', () => {
    const authSection = document.getElementById('authSection');
    const mainSection = document.getElementById('mainSection');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const logoutBtn = document.getElementById('logoutBtn');
    const userDisplay = document.getElementById('userDisplay');

    // Check if already logged in
    if (getToken()) {
        showMain();
    }

    // Login
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('loginUsername').value.trim();
        const password = document.getElementById('loginPassword').value;

        try {
            const data = await apiLogin(username, password);
            setToken(data.access_token);
            showMain();
        } catch (err) {
            alert('登录失败：' + err.message);
        }
    });

    // Register
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('regUsername').value.trim();
        const password = document.getElementById('regPassword').value;
        const coupleCode = document.getElementById('regCoupleCode').value.trim();

        if (password.length < 3) {
            alert('密码至少 3 位');
            return;
        }

        try {
            const data = await apiRegister(username, password, coupleCode);
            setToken(data.access_token);
            showMain();
        } catch (err) {
            alert('注册失败：' + err.message);
        }
    });

    // Logout
    logoutBtn.addEventListener('click', () => {
        clearToken();
        authSection.style.display = '';
        mainSection.style.display = 'none';
        logoutBtn.style.display = 'none';
        userDisplay.textContent = '';
    });

    function showMain() {
        authSection.style.display = 'none';
        mainSection.style.display = '';
        logoutBtn.style.display = '';
        userDisplay.textContent = '';

        // Init components
        initMomentForm();
        initAnniversary();
        loadTimeline();
        loadAnniversaries();
    }
});
