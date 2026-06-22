/**
 * AI Meeting Assistant — Content Script
 *
 * Injected into Google Meet and Zoom pages.
 * Detects meeting context (URL, title, platform) and sends to the background worker.
 */

(function () {
  'use strict';

  // ─── Detect Platform ────────────────────────────────────────────────────────
  const url = window.location.href;
  let platform = 'unknown';
  let meetingTitle = document.title;

  if (url.includes('meet.google.com')) {
    platform = 'google-meet';
  } else if (url.includes('zoom.us')) {
    platform = 'zoom';
  }

  // ─── Send page info to background worker ─────────────────────────────────────
  function sendPageInfo() {
    const info = {
      platform,
      url: window.location.href,
      title: document.title,
      timestamp: Date.now(),
    };

    chrome.runtime.sendMessage(
      { type: 'PAGE_INFO', data: info },
      (response) => {
        if (chrome.runtime.lastError) {
          // Extension context invalidated — ignore
          return;
        }
        if (response?.received) {
          console.log('[MeetAssist] Page info sent to background');
        }
      }
    );
  }

  // Send immediately and watch for title changes (meeting name updates)
  sendPageInfo();

  const titleObserver = new MutationObserver(() => {
    if (document.title !== meetingTitle) {
      meetingTitle = document.title;
      sendPageInfo();
    }
  });

  const titleElement = document.querySelector('title');
  if (titleElement) {
    titleObserver.observe(titleElement, { childList: true });
  }

  // ─── Visual indicator (optional) ─────────────────────────────────────────────
  function injectIndicator() {
    if (document.getElementById('meet-assist-indicator')) return;

    const indicator = document.createElement('div');
    indicator.id = 'meet-assist-indicator';
    indicator.innerHTML = '🎙️ AI Meeting Assistant';
    indicator.style.cssText = `
      position: fixed;
      bottom: 16px;
      right: 16px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 8px 16px;
      border-radius: 24px;
      font-family: 'Segoe UI', sans-serif;
      font-size: 13px;
      font-weight: 500;
      z-index: 999999;
      box-shadow: 0 4px 16px rgba(102, 126, 234, 0.4);
      cursor: pointer;
      transition: all 0.3s ease;
      opacity: 0.9;
    `;

    indicator.addEventListener('mouseenter', () => {
      indicator.style.opacity = '1';
      indicator.style.transform = 'scale(1.05)';
    });
    indicator.addEventListener('mouseleave', () => {
      indicator.style.opacity = '0.9';
      indicator.style.transform = 'scale(1)';
    });

    // Click to open extension popup
    indicator.addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });
    });

    document.body.appendChild(indicator);
  }

  // Wait for body to be ready
  if (document.body) {
    injectIndicator();
  } else {
    document.addEventListener('DOMContentLoaded', injectIndicator);
  }

  // ─── Listen for recording state changes ───────────────────────────────────────
  chrome.runtime.onMessage.addListener((message) => {
    const indicator = document.getElementById('meet-assist-indicator');
    if (!indicator) return;

    if (message.type === 'RECORDING_STARTED') {
      indicator.innerHTML = '🔴 Recording...';
      indicator.style.background = 'linear-gradient(135deg, #f5365c 0%, #f56036 100%)';
    }

    if (message.type === 'RECORDING_STOPPED') {
      indicator.innerHTML = '🎙️ AI Meeting Assistant';
      indicator.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
    }
  });

  console.log(`[MeetAssist] Content script loaded on ${platform}`);
})();
