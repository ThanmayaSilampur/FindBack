document.addEventListener('DOMContentLoaded', function() {
    const navToggle = document.querySelector('#navToggle');
    const navLinks = document.querySelector('#navLinks');

    if (navToggle && navLinks) {
        navToggle.addEventListener('click', function() {
            const isOpen = navLinks.classList.toggle('open');
            navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
    }
});
