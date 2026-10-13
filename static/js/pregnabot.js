document.addEventListener('DOMContentLoaded', function () {
  var menuButton = document.querySelector('[data-sidebar-toggle]');
  var closeTargets = document.querySelectorAll('[data-sidebar-close]');

  function setSidebarOpen(isOpen) {
    document.body.classList.toggle('sidebar-open', isOpen);
    if (menuButton) {
      menuButton.setAttribute('aria-expanded', String(isOpen));
      menuButton.setAttribute('aria-label', isOpen ? 'Close navigation' : 'Open navigation');
    }
  }

  if (menuButton) {
    menuButton.addEventListener('click', function () {
      setSidebarOpen(!document.body.classList.contains('sidebar-open'));
    });
  }

  closeTargets.forEach(function (target) {
    target.addEventListener('click', function () {
      setSidebarOpen(false);
    });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') setSidebarOpen(false);
  });

  document.querySelectorAll('[data-dismiss-flash]').forEach(function (button) {
    button.addEventListener('click', function () {
      button.closest('.flash-message').remove();
    });
  });

  var stream = document.querySelector('.chat-stream');
  if (stream) {
    stream.scrollTop = stream.scrollHeight;
    var input = document.getElementById('chat-question');
    if (input) input.focus();
  }
});
