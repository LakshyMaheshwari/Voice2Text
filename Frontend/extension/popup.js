/**
 * AI Meeting Assistant — Popup Script
 *
 * Handles:
 * - Authentication (login/register)
 * - Recording start/stop
 * - Real-time transcript display
 * - Timer and status updates
 */

// ─── Configuration ──────────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:5000/api';

// ─── State ──────────────────────────────────────────────────────────────────────
let state = {
  token: null,
  user: null,
  isRecording: false,
  meetingId: null,
  timerInterval: null,
  timerSeconds: 0,
  segmentCount: 0,
  speakerColors: {},
  speakerIndex: 0,
};

// ─── DOM Elements ───────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const authView = $('#auth-view');
const mainView = $('#main-view');
const loginForm = $('#login-form');
const registerForm = $('#register-form');
const authError = $('#auth-error');
const loginBtn = $('#login-btn');
const registerBtn = $('#register-btn');
const userAvatar = $('#user-avatar');
const userName = $('#user-name');
const logoutBtn = $('#logout-btn');
const meetingPlatform = $('#meeting-platform');
const meetingTitle = $('#meeting-title');
const recordBtn = $('#record-btn');
const recordIcon = $('#record-icon');
const recordLabel = $('#record-label');
const recordingTimer = $('#recording-timer');
const timerText = $('#timer-text');
const transcriptSection = $('#transcript-section');
const transcriptFeed = $('#transcript-feed');
const segmentCount = $('#segment-count');
const statusBar = $('#status-bar');
const progressBar = $('#progress-bar');
const statusText = $('#status-text');

// ─── Auth Tabs ──────────────────────────────────────────────────────────────────
document.querySelectorAll('.auth-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.auth-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');

    const target = tab.dataset.tab;
    loginForm.classList.toggle('active', target === 'login');
    registerForm.classList.toggle('active', target === 'register');
    hideError();
  });
});

// ─── API Helpers ────────────────────────────────────────────────────────────────
async function apiRequest(endpoint, method = 'GET', body = null) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) {
    headers['Authorization'] = `Bearer ${state.token}`;
  }

  const options = { method, headers };
  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_BASE}${endpoint}`, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || 'Request failed');
  }

  return data;
}

// ─── Error Display ──────────────────────────────────────────────────────────────
function showError(message) {
  authError.textContent = message;
  authError.classList.add('visible');
}

function hideError() {
  authError.classList.remove('visible');
}

// ─── Auth Handlers ──────────────────────────────────────────────────────────────
loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();
  loginBtn.classList.add('loading');

  try {
    const email = $('#login-email').value;
    const password = $('#login-password').value;
    const data = await apiRequest('/auth/login', 'POST', { email, password });

    state.token = data.token;
    state.user = data.user;
    await chrome.storage.local.set({ token: data.token, user: data.user });

    showMainView();
  } catch (error) {
    showError(error.message);
  } finally {
    loginBtn.classList.remove('loading');
  }
});

registerForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();
  registerBtn.classList.add('loading');

  try {
    const name = $('#register-name').value;
    const email = $('#register-email').value;
    const password = $('#register-password').value;
    const data = await apiRequest('/auth/register', 'POST', { name, email, password });

    state.token = data.token;
    state.user = data.user;
    await chrome.storage.local.set({ token: data.token, user: data.user });

    showMainView();
  } catch (error) {
    showError(error.message);
  } finally {
    registerBtn.classList.remove('loading');
  }
});

// ─── Logout ─────────────────────────────────────────────────────────────────────
logoutBtn.addEventListener('click', async () => {
  state.token = null;
  state.user = null;
  await chrome.storage.local.remove(['token', 'user']);
  showAuthView();
});

// ─── View Switching ─────────────────────────────────────────────────────────────
function showAuthView() {
  authView.classList.add('active');
  mainView.classList.remove('active');
}

function showMainView() {
  authView.classList.remove('active');
  mainView.classList.add('active');

  // Update user info
  if (state.user) {
    userAvatar.textContent = state.user.name ? state.user.name.charAt(0).toUpperCase() : 'U';
    userName.textContent = state.user.name || 'User';
  }

  // Check for meeting context
  loadMeetingContext();
}

// ─── Meeting Context ────────────────────────────────────────────────────────────
async function loadMeetingContext() {
  const data = await chrome.storage.local.get('pageInfo');
  if (data.pageInfo) {
    const { platform, title } = data.pageInfo;
    const platformNames = {
      'google-meet': '🎥 Google Meet',
      'zoom': '📹 Zoom',
      'unknown': '🌐 Browser Tab',
    };
    meetingPlatform.innerHTML = `
      <span class="platform-icon">${platform === 'google-meet' ? '🎥' : platform === 'zoom' ? '📹' : '🌐'}</span>
      <span class="platform-name">${platformNames[platform] || 'Browser Tab'} — ${title}</span>
    `;
    meetingTitle.value = title || '';
  }
}

// ─── Recording ──────────────────────────────────────────────────────────────────
recordBtn.addEventListener('click', async () => {
  if (state.isRecording) {
    await stopRecording();
  } else {
    await startRecording();
  }
});

async function startRecording() {
  try {
    // Create meeting on backend
    const title = meetingTitle.value || 'Untitled Meeting';
    const meeting = await apiRequest('/meetings', 'POST', { title });

    state.meetingId = meeting._id;

    // Get current tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Send start command to background
    const result = await chrome.runtime.sendMessage({
      type: 'START_RECORDING',
      meetingId: meeting._id,
      token: state.token,
      tabId: tab.id,
    });

    if (result.success) {
      state.isRecording = true;
      updateRecordingUI(true);
      startTimer();
    } else {
      showStatusMessage(`Failed: ${result.error}`, 'error');
    }
  } catch (error) {
    console.error('Start recording error:', error);
    showStatusMessage(`Error: ${error.message}`, 'error');
  }
}

async function stopRecording() {
  try {
    const result = await chrome.runtime.sendMessage({ type: 'STOP_RECORDING' });

    if (result.success) {
      state.isRecording = false;
      updateRecordingUI(false);
      stopTimer();
      showStatusBar('Processing your meeting...');
    }
  } catch (error) {
    console.error('Stop recording error:', error);
  }
}

function updateRecordingUI(isRecording) {
  if (isRecording) {
    recordBtn.classList.add('recording');
    recordLabel.textContent = 'Stop Recording';
    recordIcon.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
        <rect x="6" y="6" width="12" height="12" rx="2"/>
      </svg>
    `;
    recordingTimer.style.display = 'flex';
    transcriptSection.style.display = 'block';
    transcriptFeed.innerHTML = '<div class="transcript-empty"><p>Waiting for speech...</p></div>';
  } else {
    recordBtn.classList.remove('recording');
    recordLabel.textContent = 'Start Recording';
    recordIcon.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="12" cy="12" r="8"/>
      </svg>
    `;
    recordingTimer.style.display = 'none';
  }
}

// ─── Timer ──────────────────────────────────────────────────────────────────────
function startTimer() {
  state.timerSeconds = 0;
  timerText.textContent = '00:00';
  state.timerInterval = setInterval(() => {
    state.timerSeconds++;
    const mins = String(Math.floor(state.timerSeconds / 60)).padStart(2, '0');
    const secs = String(state.timerSeconds % 60).padStart(2, '0');
    timerText.textContent = `${mins}:${secs}`;
  }, 1000);
}

function stopTimer() {
  if (state.timerInterval) {
    clearInterval(state.timerInterval);
    state.timerInterval = null;
  }
}

// ─── Transcript Display ─────────────────────────────────────────────────────────
function getSpeakerColor(speaker) {
  if (!state.speakerColors[speaker]) {
    state.speakerColors[speaker] = state.speakerIndex++;
  }
  return `speaker-${state.speakerColors[speaker] % 6}`;
}

function addTranscriptSegment(data) {
  // Remove empty state message
  const emptyMsg = transcriptFeed.querySelector('.transcript-empty');
  if (emptyMsg) {
    emptyMsg.remove();
  }

  const segment = document.createElement('div');
  segment.className = 'transcript-segment';

  const colorClass = getSpeakerColor(data.speaker);
  const startMin = Math.floor(data.start / 60);
  const startSec = Math.floor(data.start % 60);
  const timeStr = `${String(startMin).padStart(2, '0')}:${String(startSec).padStart(2, '0')}`;

  segment.innerHTML = `
    <div class="segment-speaker ${colorClass}">${data.speaker}</div>
    <div class="segment-text">${escapeHtml(data.text)}</div>
    <div class="segment-time">${timeStr}</div>
  `;

  transcriptFeed.appendChild(segment);
  transcriptFeed.scrollTop = transcriptFeed.scrollHeight;

  state.segmentCount++;
  segmentCount.textContent = `${state.segmentCount} segment${state.segmentCount !== 1 ? 's' : ''}`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ─── Status Bar ─────────────────────────────────────────────────────────────────
function showStatusBar(message) {
  statusBar.style.display = 'block';
  statusText.textContent = message;
  progressBar.style.width = '60%';
}

function showStatusMessage(message, type = 'info') {
  statusBar.style.display = 'block';
  statusText.textContent = message;
  progressBar.style.width = type === 'error' ? '100%' : '60%';
  progressBar.style.background = type === 'error'
    ? 'var(--gradient-danger)'
    : 'var(--gradient-primary)';

  if (type === 'error') {
    setTimeout(() => {
      statusBar.style.display = 'none';
    }, 5000);
  }
}

// ─── Listen for messages from background worker ─────────────────────────────────
chrome.runtime.onMessage.addListener((message) => {
  switch (message.type) {
    case 'transcription':
      if (message.data.isFinal) {
        addTranscriptSegment(message.data);
      }
      break;

    case 'processing-status':
      if (message.data.status === 'completed') {
        progressBar.style.width = '100%';
        statusText.textContent = '✅ Meeting processed! Transcript and summary ready.';
        setTimeout(() => {
          statusBar.style.display = 'none';
        }, 5000);
      } else if (message.data.status === 'failed') {
        progressBar.style.width = '100%';
        progressBar.style.background = 'var(--gradient-danger)';
        statusText.textContent = '❌ Processing failed. Please try again.';
      } else {
        statusText.textContent = message.data.progress || 'Processing...';
      }
      break;

    case 'error':
      showStatusMessage(message.data.message || 'An error occurred', 'error');
      break;
  }
});

// ─── Initialize ─────────────────────────────────────────────────────────────────
async function init() {
  // Check for saved auth
  const data = await chrome.storage.local.get(['token', 'user']);

  if (data.token && data.user) {
    state.token = data.token;
    state.user = data.user;

    // Verify token is still valid
    try {
      const me = await apiRequest('/auth/me');
      state.user = me;
      showMainView();
    } catch {
      // Token expired
      await chrome.storage.local.remove(['token', 'user']);
      showAuthView();
    }
  } else {
    showAuthView();
  }

  // Check recording state
  const bgState = await chrome.runtime.sendMessage({ type: 'GET_STATE' });
  if (bgState && bgState.isRecording) {
    state.isRecording = true;
    state.meetingId = bgState.meetingId;
    updateRecordingUI(true);
    startTimer();
  }
}

init();
