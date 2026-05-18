if (window.rcmail) {
  rcmail.addEventListener('init', function () {
    function labelButton() {
      var buttons = document.querySelectorAll('.report-phish, [command="plugin.report_phish"]');
      buttons.forEach(function (button) {
        button.setAttribute('title', 'Report Phish');
        button.setAttribute('aria-label', 'Report Phish');
        var inner = button.querySelector('.inner') || button;
        inner.textContent = 'Report Phish';
      });
    }
    labelButton();
    window.setTimeout(labelButton, 500);
    window.setTimeout(labelButton, 1500);

    rcmail.register_command('plugin.report_phish', function () {
      var uid = rcmail.env.uid;
      if (!uid && rcmail.message_list) {
        var selection = rcmail.message_list.get_selection();
        uid = selection && selection.length ? selection.join(',') : '';
      }
      if (!uid) {
        rcmail.display_message(rcmail.gettext('selectmessage', 'report_phish'), 'warning');
        return;
      }
      var lock = rcmail.set_busy(true, 'loading');
      rcmail.http_post('plugin.report_phish', {
        _uid: uid,
        _mbox: rcmail.env.mailbox || 'INBOX'
      }, lock);
    }, true);
  });
}
