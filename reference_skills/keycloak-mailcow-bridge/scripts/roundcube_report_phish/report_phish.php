<?php

class report_phish extends rcube_plugin
{
    public $task = 'mail';

    public function init()
    {
        $this->add_texts('localization/', true);
        $this->include_script('report_phish.js');
        $this->register_action('plugin.report_phish', array($this, 'report'));
        $this->add_button(array(
            'command' => 'plugin.report_phish',
            'type' => 'link',
            'label' => 'report_phish.reportphish',
            'title' => 'report_phish.reportphish',
            'class' => 'button report-phish',
            'classact' => 'button report-phish',
            'innerclass' => 'inner',
        ), 'toolbar');
    }

    public function report()
    {
        $rcmail = rcmail::get_instance();
        $uid = rcube_utils::get_input_value('_uid', rcube_utils::INPUT_POST);
        $mailbox = rcube_utils::get_input_value('_mbox', rcube_utils::INPUT_POST);
        if (!$mailbox) {
            $mailbox = $rcmail->storage->get_folder();
        }
        if (!$uid) {
            $rcmail->output->show_message('report_phish.selectmessage', 'warning');
            $rcmail->output->send();
            return;
        }

        $uids = explode(',', (string)$uid);
        $uid = trim((string)$uids[0]);
        try {
            $rcmail->storage->set_folder($mailbox);
            $message = new rcube_message($uid);
            $headers = $message->headers;
            $raw_headers = $rcmail->storage->get_raw_headers($uid);
            $raw_body = $rcmail->storage->get_raw_body($uid);
            $raw = trim((string)$raw_headers) . "\r\n\r\n" . (string)$raw_body;
            $mailbox_user = $rcmail->user->get_username();

            $payload = array(
                'mailbox' => $mailbox_user,
                'folder' => $mailbox,
                'uid' => $uid,
                'sender' => (string)($headers->from ?? 'unknown'),
                'subject' => (string)($headers->subject ?? '(no subject)'),
                'message_id' => (string)($headers->messageID ?? ''),
                'raw' => $raw,
            );
            $result = $this->post_report($payload);
            if (empty($result['ok'])) {
                $rcmail->output->show_message('report_phish.failed', 'error');
            } else {
                $this->mark_reported($rcmail, $uid, $mailbox);
                $rcmail->output->show_message('report_phish.reported', 'confirmation');
            }
        } catch (Exception $exc) {
            $rcmail->output->show_message('report_phish.failed', 'error');
        }
        $rcmail->output->send();
    }

    private function post_report($payload)
    {
        $endpoint = getenv('REPORT_PHISH_ENDPOINT') ?: 'http://host.docker.internal:2581/demo-report';
        $token = getenv('REPORT_PHISH_TOKEN') ?: '';
        if ($token === '') {
            return array('ok' => false);
        }
        $ch = curl_init($endpoint);
        curl_setopt_array($ch, array(
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_HTTPHEADER => array(
                'Content-Type: application/json',
                'X-Report-Phish-Token: ' . $token,
            ),
            CURLOPT_POSTFIELDS => json_encode($payload),
            CURLOPT_TIMEOUT => 20,
        ));
        $body = curl_exec($ch);
        $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        if ($body === false || $status >= 400) {
            return array('ok' => false);
        }
        $decoded = json_decode($body, true);
        return is_array($decoded) ? $decoded : array('ok' => false);
    }

    private function mark_reported($rcmail, $uid, $mailbox)
    {
        try {
            $rcmail->storage->set_folder($mailbox);
            $rcmail->storage->set_flag($uid, 'SEEN');
            $folders = $rcmail->storage->list_folders();
            if (!in_array('Junk', $folders, true)) {
                $rcmail->storage->create_folder('Junk');
            }
            $rcmail->storage->copy_message($uid, 'Junk');
        } catch (Exception $exc) {
            return;
        }
    }
}
