/* chapterEditor — Alpine-компонент редактора главы (FR-WRITE-05, BR-78).
 *
 * Отвечает за одно: **набранный текст не должен пропадать**. До него
 * индикатор «Сақталмаған өзгеріс бар» честно показывал, что изменения не
 * сохранены, и ничего с этим не делал — сохранить мог только сам автор,
 * нажав кнопку.
 *
 * Две страховки, разные по надёжности, и обе нужны:
 *
 *  1. **Сервер** — debounce в 3 секунды после последнего нажатия. Спасает
 *     от закрытой вкладки, разряженного телефона и смены устройства.
 *     Доступен только у непубличной работы: у публичной записанная глава
 *     сразу видна читателю, и автосохранение выкладывало бы недописанное
 *     само (см. `views/write.chapter_autosave`).
 *  2. **localStorage** — на каждое нажатие, синхронно и без сети. Спасает
 *     там, где первая бессильна: офлайн, упавший сервер, публичная работа.
 *     Найденную при загрузке версию компонент **не подставляет молча** —
 *     он предлагает её восстановить: молчаливая подмена текста хуже его
 *     потери, потому что необратима и незаметна.
 *
 * Файл подключается блоком `page_scripts` — то есть с `defer` и ДО
 * alpine.min.js: слушатель `alpine:init` обязан встать раньше старта
 * Alpine, иначе имя компонента останется неизвестным.
 */
(function () {
    var DEBOUNCE_MS = 3000;
    var STASH_PREFIX = 'bp-chapter-draft:';

    /* localStorage бывает недоступен целиком: приватное окно, выключенные
     * site data, квота. Обращение к нему тогда бросает, и уронить редактор
     * ради страховки — ровно та потеря текста, от которой она защищает. */
    function safeStorage(action, fallback) {
        try {
            return action();
        } catch (e) {
            return fallback;
        }
    }

    document.addEventListener('alpine:init', function () {
        Alpine.data('chapterEditor', function (config) {
            return {
                dirty: false,
                saving: false,
                failed: false,
                savedAt: '',
                /* Найденная в браузере несохранённая версия — до тех пор,
                 * пока автор не решит, что с ней делать. */
                stash: null,

                autosaveUrl: config.autosaveUrl,
                editUrl: '',
                enabled: !!config.enabled,
                timer: null,
                key: STASH_PREFIX + config.storyKey + ':' + config.chapterKey,

                /* Поля ищутся внутри самого компонента, а не через `x-ref`:
                 * заголовок рисует общий `input_field.html`, и ставить туда
                 * ref ради одной страницы значит менять компонент под неё.
                 *
                 * `$root`, а не `$el`: `$el` — элемент, на котором сейчас
                 * вычисляется выражение, то есть в `@click` это сама кнопка.
                 * Из `init()` разницы не видно (там `$el` и есть корень), а
                 * из обработчика поиск уходил внутрь кнопки и возвращал
                 * `null` — восстановление падало молча, в консоль. */
                titleEl: function () {
                    return this.$root.querySelector('input[name="title"]');
                },

                bodyEl: function () {
                    return this.$root.querySelector('textarea[name="body"]');
                },

                init: function () {
                    var self = this;
                    var found = safeStorage(function () {
                        return JSON.parse(localStorage.getItem(self.key) || 'null');
                    }, null);
                    /* Совпало с тем, что уже на странице, — восстанавливать
                     * нечего: прошлый заход закончился сохранением. */
                    if (found && found.body !== this.bodyEl().value) {
                        this.stash = found;
                    } else if (found) {
                        this.forget();
                    }
                },

                /* ── Ввод ──────────────────────────────────────────────── */
                touch: function () {
                    this.dirty = true;
                    this.failed = false;
                    this.remember();
                    if (this.enabled) {
                        clearTimeout(this.timer);
                        this.timer = setTimeout(this.save.bind(this), DEBOUNCE_MS);
                    }
                },

                fields: function () {
                    return {
                        title: this.titleEl() ? this.titleEl().value : '',
                        body: this.bodyEl() ? this.bodyEl().value : ''
                    };
                },

                /* ── Страховка в браузере ──────────────────────────────── */
                remember: function () {
                    var payload = this.fields();
                    payload.at = new Date().toISOString();
                    var self = this;
                    safeStorage(function () {
                        localStorage.setItem(self.key, JSON.stringify(payload));
                    }, null);
                },

                forget: function () {
                    var self = this;
                    safeStorage(function () {
                        localStorage.removeItem(self.key);
                    }, null);
                },

                restore: function () {
                    if (!this.stash) { return; }
                    var title = this.titleEl();
                    if (title) { title.value = this.stash.title || ''; }
                    this.bodyEl().value = this.stash.body || '';
                    /* Счётчик знаков — соседний компонент, и число в нём
                     * посчитано по прежнему тексту. */
                    this.bodyEl().dispatchEvent(new Event('input', { bubbles: true }));
                    this.stash = null;
                },

                discard: function () {
                    this.stash = null;
                    this.forget();
                },

                /* ── Страховка на сервере ──────────────────────────────── */

                /* Совпадает ли то, что в полях сейчас, с тем, что ушло на
                 * сервер. Ответ приходит к снимку, сделанному несколько
                 * секунд назад, и за это время автор успевает дописать. */
                matches: function (sent) {
                    var now = this.fields();
                    return now.title === sent.title && now.body === sent.body;
                },

                save: function () {
                    if (!this.enabled || this.saving) { return; }
                    var values = this.fields();
                    /* Пустое автосохранением не пишется: заводить главу из
                     * нуля знаков — не спасение текста, а мусор в кабинете. */
                    if (!values.title.trim() && !values.body.trim()) { return; }

                    var body = new FormData();
                    body.append('title', values.title);
                    body.append('body', values.body);
                    body.append('csrfmiddlewaretoken', config.csrfToken);

                    var self = this;
                    this.saving = true;
                    fetch(this.autosaveUrl, {
                        method: 'POST',
                        body: body,
                        headers: { 'X-Requested-With': 'XMLHttpRequest' },
                        credentials: 'same-origin'
                    }).then(function (response) {
                        return response.ok ? response.json() : Promise.reject(response);
                    }).then(function (result) {
                        self.saving = false;
                        self.savedAt = result.saved_at;
                        /* Сохранён **снимок**, а не то, что в полях сейчас.
                         *
                         * Между отправкой и ответом автор продолжает
                         * писать, и безусловные `dirty = false` плюс
                         * `forget()` стирали браузерную страховку для
                         * текста, которого на сервере нет, — и говорили
                         * при этом «сақталды». Окно узкое, ровно
                         * длительность запроса, но компонент существует
                         * ради того, чтобы текст не пропадал, и врать в
                         * этот момент он не вправе.
                         *
                         * Разошлось — оставляем страховку и метку
                         * «несохранённое», а следующий проход назначаем
                         * сами: `touch()` больше не сработает, если автор
                         * как раз допечатал и убрал руки. */
                        if (self.matches(values)) {
                            self.dirty = false;
                            self.forget();
                        } else {
                            clearTimeout(self.timer);
                            self.timer = setTimeout(self.save.bind(self), DEBOUNCE_MS);
                        }
                        /* Первый автосейв новой главы присвоил ей номер:
                         * дальше пишем в неё, а не заводим следующую. */
                        if (result.autosave_url) {
                            self.autosaveUrl = result.autosave_url;
                        }
                        if (result.url && self.editUrl !== result.url) {
                            self.editUrl = result.url;
                            history.replaceState(null, '', result.url);
                        }
                    }).catch(function () {
                        /* Сеть отпала или сервер отказал: страховка в
                         * браузере остаётся, и об этом говорится вслух. */
                        self.saving = false;
                        self.failed = true;
                    });
                }
            };
        });
    });
})();
