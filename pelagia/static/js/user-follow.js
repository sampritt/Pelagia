(() => {
    document.querySelectorAll('[data-user-follow]').forEach((form) => {
        const button = form.querySelector('button');
        const desired = form.elements.following;
        const status = form.querySelector('[role="status"]');
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (button.disabled) return;
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            status.textContent = '';
            try {
                const response = await fetch(form.action, {
                    method: 'POST', body: new FormData(form), credentials: 'same-origin',
                    headers: {'X-Requested-With': 'fetch'},
                });
                if (!response.ok) throw new Error('Follow failed');
                const data = await response.json();
                button.textContent = data.following ? 'Following' : 'Follow';
                button.setAttribute('aria-pressed', String(data.following));
                button.classList.toggle('is-following', data.following);
                desired.value = data.following ? 'false' : 'true';
                status.textContent = data.following ? 'Added to your feed.' : 'Removed from your feed.';
            } catch (_) {
                status.textContent = 'Couldn’t update follow. Please try again.';
            } finally {
                button.disabled = false;
                button.removeAttribute('aria-busy');
            }
        });
    });
})();
