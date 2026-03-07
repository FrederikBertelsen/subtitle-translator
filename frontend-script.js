(function () {
    // Edit these variables to match your .env values
    var API_BASE = ''; // no trailing slash
    var API_KEY = '';
    var TRANSLATE_PATH = '';
    var JOBS_BASE = '';

    function log() {
        var args = Array.prototype.slice.call(arguments);
        args.unshift('[SubtitleGen]');
        console.log.apply(console, args);
    }

    var mediaTitle = '';
    var mediaType = '';

    function waitAndRun() {
        var maxAttempts = 50;
        var attempts = 0;
        var interval = setInterval(function () {
            attempts++;

            var span = document.querySelector('div.headerRight > button > span.material-icons.person');
            var userBtn = span ? (span.parentElement || (span.closest ? span.closest('button') : null)) : document.querySelector('div.headerRight > button');

            var buttonsContainer = document.querySelector('.mainDetailButtons');
            if (!buttonsContainer) {
                var playArrow = document.querySelector('.mainDetailButtons > button:not([class*="hide"]) > div.detailButton-content > span.play_arrow');
                if (playArrow) {
                    var el = playArrow.parentElement;
                    el = el && el.parentElement;
                    el = el && el.parentElement;
                    buttonsContainer = el || null;
                }
            }

            if (userBtn && buttonsContainer) {
                clearInterval(interval);
                run(userBtn, buttonsContainer);
            } else if (attempts >= maxAttempts) {
                clearInterval(interval);
                if (!userBtn) log('Timed out waiting for user button.');
                if (!buttonsContainer) log('Timed out waiting for main detail buttons.');
            }
        }, 100);
    }

    function run(userBtn, buttonsContainer) {
        var span = userBtn ? userBtn.querySelector('span.material-icons.person') : null;
        var username = '';
        if (userBtn) {
            username = userBtn.getAttribute('title') || userBtn.title || (span ? (span.textContent || '') : '');
            username = (username || '').trim();
        }
        if (username !== 'Frederik') {
            log('Not Frederik — aborting. Found username:', username);
            return;
        }
        log('User is Frederik — proceeding.');

        mediaType = detectMediaType();

        var waitAttempts = 0;
        var maxWaitAttempts = 30; // ~4.5s with the interval below
        var waitIntervalMs = 150;

        function proceedWhenTitleReady() {
            var mediaEl = document.querySelector('div.nameContainer h1');
            mediaTitle = mediaEl ? (mediaEl.innerText || '').trim() : '';
            if (!mediaTitle && waitAttempts < maxWaitAttempts) {
                waitAttempts++;
                setTimeout(proceedWhenTitleReady, waitIntervalMs);
                return;
            }
            if (!mediaTitle) {
                console.error('[SubtitleGen] Error: media title not found (div.nameContainer h1). Aborting.');
                return;
            }

            var hasEng = false;
            var hasDa = false;

            if (mediaType === 'movie') {
                var select = document.querySelector('select.selectSubtitles');
                if (!select) {
                    console.error('[SubtitleGen] Error: No subtitles selector found (select.selectSubtitles). Aborting.');
                    return;
                }

                var options = select.querySelectorAll('option');
                var candidates = [];
                for (var i = 0; i < options.length; i++) {
                    if (options[i].value !== '-1') candidates.push(options[i]);
                }

                var reEng = /\benglish\b|\beng\b/i;
                var reDa = /\bdanish\b|\bda\b|\bdansk\b/i;
                for (i = 0; i < candidates.length; i++) {
                    var t = (candidates[i].textContent || candidates[i].innerText || '').trim();
                    if (reEng.test(t)) hasEng = true;
                    if (reDa.test(t)) hasDa = true;
                }
                log('Subtitle scan: hasEnglish=' + hasEng + ' hasDanish=' + hasDa);
            } else {
                log('TV show — skipping subtitle scan, showing all buttons.');
            }

            var container = document.getElementById('subtitle-gen-container');
            if (!container) {
                container = document.createElement('div');
                container.id = 'subtitle-gen-container';
                container.style.marginTop = '8px';
                buttonsContainer.appendChild(container);
            } else {
                container.innerHTML = '';
                if (!container.parentElement) buttonsContainer.appendChild(container);
            }

            function makeButton(langCode, label) {
                if (container.querySelector('.gen-' + langCode + '-btn')) return;
                var wrapper = document.createElement('div');
                wrapper.style.display = 'inline-flex';
                wrapper.style.alignItems = 'center';
                wrapper.style.gap = '8px';
                wrapper.style.marginRight = '8px';

                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'gen-' + langCode + '-btn';
                btn.textContent = label;
                btn.style.padding = '6px 10px';
                btn.style.cursor = 'pointer';

                var status = document.createElement('span');
                status.className = 'gen-' + langCode + '-status';
                status.style.fontSize = '0.9em';
                status.style.color = '#fff';
                status.textContent = '';

                wrapper.appendChild(btn);
                wrapper.appendChild(status);
                container.appendChild(wrapper);

                btn.addEventListener('click', function () { startGeneration(btn, status, langCode); });
            }

            if (!hasEng) makeButton('en', 'Generate english subtitles');
            if (!hasDa) makeButton('da', 'Generate danish subtitles');

            if (hasEng && hasDa) {
                var note = document.createElement('div');
                note.textContent = 'English and Danish subtitles already available.';
                note.style.fontSize = '0.9em';
                note.style.color = '#fff';
                container.appendChild(note);
            }
        }

        proceedWhenTitleReady();
    }

    function detectMediaType() {
        // Determine by presence of Season element
        if (document.querySelector('div[data-type="Season"]')) {
            return 'tvshow';
        }
        return 'movie';
    }

    function startGeneration(button, statusEl, lang) {
        if (mediaType === 'movie') button.disabled = true;
        statusEl.textContent = 'Starting...';

        var apiBase = (API_BASE || '').replace(/\/+$/, '');
        var translatePath = TRANSLATE_PATH || '/translate';
        var jobsBase = JOBS_BASE || '/jobs';
        var mediaName = mediaTitle || '';

        // Validate required information before sending any requests
        if (!mediaName) {
            console.error('[SubtitleGen] Error: missing media name; aborting.');
            if (mediaType === 'movie') button.disabled = false;
            return;
        }
        if (!apiBase) {
            console.error('[SubtitleGen] Error: API_BASE not set; aborting.');
            if (mediaType === 'movie') button.disabled = false;
            return;
        }

        if (!API_KEY) {
            var key = prompt('Enter X-API-Key for translation API:');
            if (!key) {
                console.error('[SubtitleGen] Error: no API key provided; aborting.');
                if (mediaType === 'movie') button.disabled = false;
                return;
            }
            API_KEY = key;
        }

        var translateUrl = apiBase + translatePath + '?name=' + encodeURIComponent(mediaName) + '&lang=' + encodeURIComponent(lang) + '&type=' + encodeURIComponent(mediaType);
        log('POST ' + translateUrl);

        var xhr = new XMLHttpRequest();
        xhr.open('POST', translateUrl);
        xhr.setRequestHeader('X-API-Key', API_KEY);
        xhr.onload = function () {
            if (xhr.status < 200 || xhr.status >= 300) {
                console.error('[SubtitleGen] Translate request failed', xhr.status, xhr.responseText);
                if (mediaType === 'movie') button.disabled = false;
                return;
            }
            var body = null;
            try { body = JSON.parse(xhr.responseText); } catch (e) { body = null; }
            var jobId = body && (body.job_id || body.jobId || body.job);
            if (!jobId) {
                console.error('[SubtitleGen] No job_id returned from /translate', body);
                if (mediaType === 'movie') button.disabled = false;
                return;
            }
            log('Started job', jobId);
            statusEl.textContent = 'Started: ' + jobId;

            var jobUrlBase = apiBase + jobsBase;
            var intervalId = setInterval(function () {
                var r = new XMLHttpRequest();
                r.open('GET', jobUrlBase + '/' + encodeURIComponent(jobId));
                r.setRequestHeader('X-API-Key', API_KEY);
                r.onload = function () {
                    if (r.status === 404) {
                        console.error('[SubtitleGen] Job not found', jobId);
                        clearInterval(intervalId);
                        if (mediaType === 'movie') button.disabled = false;
                        return;
                    }
                    if (r.status < 200 || r.status >= 300) {
                        console.error('[SubtitleGen] Poll error', r.status, r.responseText);
                        clearInterval(intervalId);
                        if (mediaType === 'movie') button.disabled = false;
                        return;
                    }
                    var j = null;
                    try { j = JSON.parse(r.responseText); } catch (e) { j = null; }
                    if (j && j.status === 'pending' && j.progress) {
                        var parts = j.progress.split('/');
                        var pct = Math.round((parseInt(parts[0], 10) / parseInt(parts[1], 10)) * 100);
                        statusEl.textContent = 'Translating ' + pct + '% (' + j.progress + ')';
                    } else {
                        statusEl.textContent = j && j.status ? j.status : 'unknown';
                    }
                    log('Job poll:', j);
                    if (j && j.status === 'done') {
                        statusEl.textContent = 'Done';
                        log('Job result:', j.result);
                        clearInterval(intervalId);
                        if (mediaType === 'movie') button.disabled = false;
                    } else if (j && j.status === 'failed') {
                        console.error('[SubtitleGen] Job error:', j.error);
                        clearInterval(intervalId);
                        if (mediaType === 'movie') button.disabled = false;
                    }
                };
                r.onerror = function () {
                    console.error('[SubtitleGen] Polling error');
                    clearInterval(intervalId);
                    if (mediaType === 'movie') button.disabled = false;
                };
                r.send();
            }, 1000);
        };
        xhr.onerror = function () {
            console.error('[SubtitleGen] Failed to start translation job');
            if (mediaType === 'movie') button.disabled = false;
        };
        xhr.send();
    }

    // Route watcher: start initialization when we land on a details page.
    (function () {
        var initialized = false;
        function isDetailsHash() {
            return /^#\/details(?:\b|$|\?)/.test(window.location.hash);
        }

        function onLocationChange() {
            if (isDetailsHash() && !initialized) {
                initialized = true;
                waitAndRun();
            }
            // If navigating away from details we allow re-initialization on return
            if (!isDetailsHash() && initialized) {
                initialized = false;
            }
        }

        // Hook history methods so SPA navigations trigger our watcher
        try {
            var _push = history.pushState;
            history.pushState = function () {
                var res = _push.apply(this, arguments);
                window.dispatchEvent(new Event('locationchange'));
                return res;
            };
            var _replace = history.replaceState;
            history.replaceState = function () {
                var res = _replace.apply(this, arguments);
                window.dispatchEvent(new Event('locationchange'));
                return res;
            };
        } catch (e) { /* ignore if read-only */ }

        window.addEventListener('popstate', function () { window.dispatchEvent(new Event('locationchange')); });
        window.addEventListener('hashchange', function () { window.dispatchEvent(new Event('locationchange')); });
        window.addEventListener('locationchange', onLocationChange);

        // initial attempt
        onLocationChange();
    })();

})();