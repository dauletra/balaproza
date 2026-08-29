/* Alpine-компоненты портала.
 *
 * Сюда переезжает то, у чего есть логика или что повторяется: разбор
 * события у модалок, автокомплит тегов, быстрый поиск. Однобуквенное
 * состояние (`{ open: false }` у поповера, `{ replying: false }` у формы
 * ответа) остаётся в разметке — имя для него не убирает ни одной строки, а
 * читать элемент приходится уже в двух файлах.
 *
 * Файл подключён в <head> ДО alpine.min.js и с тем же `defer`: defer
 * исполняет в порядке документа, и регистрация на `alpine:init` обязана
 * успеть до старта Alpine. Скрипт в конце body опоздал бы, а компонент
 * остался бы неизвестным именем — без единой ошибки в консоли.
 */
document.addEventListener('alpine:init', function () {

    /* Модалка, которую открывает window-событие с деталями (docs/ui.md).
     *
     * `fields` — имена ключей `event.detail`, которые становятся свойствами
     * компонента: их читают `x-text` и `:action` внутри. Отсутствующий
     * ключ даёт пустую строку, а не `undefined` в разметке.
     *
     * Escape — часть самой модалки, а не забота вызывающего: модалка,
     * которая не закрывается с клавиатуры, это ловушка для того, кто не
     * пользуется мышью.
     */
    Alpine.data('modal', function (openEvent, fields) {
        var keys = fields || [];
        var state = { open: false };
        keys.forEach(function (key) { state[key] = ''; });

        state.init = function () {
            var self = this;
            window.addEventListener(openEvent, function (e) {
                var detail = e.detail || {};
                keys.forEach(function (key) { self[key] = detail[key] || ''; });
                self.open = true;
            });
            window.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') self.open = false;
            });
        };
        return state;
    });

    /* Счётчик знаков под полем с лимитом. Начальное значение приходит с
     * сервера: до первого ввода считать нечего, а поле может быть не пустым. */
    Alpine.data('charCounter', function (initial) {
        return {
            count: initial || 0,
            recount: function (event) { this.count = event.target.value.length; }
        };
    });

    /* Свитч и чекбокс. Настоящее состояние держит сам `<input>` — он и
     * уходит в форму; компонент нужен только затем, чтобы нарисованная
     * поверх него галочка знала, что показывать. */
    Alpine.data('checkedBox', function (initial) {
        return {
            on: !!initial,
            sync: function (event) { this.on = event.target.checked; }
        };
    });

    /* Быстрый поиск (Cmd+K / Ctrl+K). Индекс тянется один раз при первом
     * открытии и живёт до перезагрузки: он маленький, а искать надо на
     * каждое нажатие клавиши. Адрес приходит параметром — {% url %} в
     * статический файл не подставить. */
    Alpine.data('searchPopup', function (indexUrl) {
        return {
            open: false,
            q: '',
            loaded: false,
            loading: false,
            index: { stories: [], authors: [], tags: [] },

            async ensureLoaded() {
                if (this.loaded || this.loading) return;
                this.loading = true;
                try {
                    const r = await fetch(indexUrl);
                    if (r.ok) this.index = await r.json();
                    this.loaded = true;
                } catch (e) { /* offline */ }
                this.loading = false;
            },

            async openPopup() {
                this.open = true;
                await this.$nextTick();
                if (this.$refs.input) this.$refs.input.focus();
                this.ensureLoaded();
            },

            close() {
                this.open = false;
                this.q = '';
            },

            filteredStories() {
                const q = this.q.trim().toLowerCase();
                if (!q) return [];
                return this.index.stories.filter(s =>
                    s.title.toLowerCase().includes(q) || s.author.toLowerCase().includes(q)
                ).slice(0, 5);
            },

            filteredAuthors() {
                const q = this.q.trim().toLowerCase();
                if (!q) return [];
                return this.index.authors.filter(a =>
                    a.name.toLowerCase().includes(q) || a.username.toLowerCase().includes(q)
                ).slice(0, 5);
            },

            filteredTags() {
                const q = this.q.trim().toLowerCase();
                if (!q) return [];
                return (this.index.tags || []).filter(t =>
                    t.name.toLowerCase().includes(q) || t.slug.toLowerCase().includes(q)
                ).slice(0, 5);
            }
        };
    });

    /* UGC-теги: чипы, автокомплит, валидация до отправки (BR-TAG-01…06).
     *
     * Словари принятых тегов и запрещённых образцов приходят через
     * `json_script`, а не аргументом: это списки на сотни строк, и в
     * атрибуте они потребовали бы экранирования кавычек в каждом имени.
     *
     * Проверка здесь — подсказка, а не защита: то же правило стоит на
     * сервере, в `forms.py`.
     */
    Alpine.data('tagInput', function (options) {
        const initial = options.initial;
        const maxTags = options.maxTags;
        const accepted = JSON.parse(document.getElementById('tag-input-accepted').textContent || '[]');
        const blocked = JSON.parse(document.getElementById('tag-input-blocked').textContent || '[]');
        const blockedSet = new Set(blocked.map(b => String(b).toLowerCase()));

        return {
            selected: Array.isArray(initial) ? [...initial] : [],
            inputValue: '',
            suggestions: [],
            showSuggestions: false,
            highlightIndex: -1,
            error: '',
            maxTags,

            onInput() {
                this.error = '';
                const q = this.inputValue.trim().toLowerCase();
                const taken = new Set(this.selected.map(t => (t.slug || t.name).toLowerCase()));
                this.suggestions = accepted
                    .filter(t => !taken.has(t.slug.toLowerCase()) && !taken.has(t.name.toLowerCase()))
                    .filter(t => !q || t.name.toLowerCase().includes(q) || t.slug.toLowerCase().includes(q))
                    .slice(0, 8);
                this.showSuggestions = true;
                this.highlightIndex = this.suggestions.length > 0 ? 0 : -1;
            },

            moveHighlight(delta) {
                if (!this.showSuggestions || this.suggestions.length === 0) return;
                this.highlightIndex = (this.highlightIndex + delta + this.suggestions.length) % this.suggestions.length;
            },

            closeSuggestions() {
                this.showSuggestions = false;
                this.highlightIndex = -1;
            },

            validateName(name) {
                const n = name.trim();
                if (n.length < 2)  return 'Тег тым қысқа (минимум 2 таңба).';
                if (n.length > 30) return 'Тег тым ұзын (максимум 30 таңба).';
                if (blockedSet.has(n.toLowerCase())) return '«' + n + '» тегін қолдануға болмайды.';
                const dup = this.selected.find(t =>
                    (t.name || '').toLowerCase() === n.toLowerCase() ||
                    (t.slug || '').toLowerCase() === n.toLowerCase()
                );
                if (dup) return 'Бұл тег қазірдің өзінде қосылған.';
                if (this.selected.length >= this.maxTags) return 'Максимум ' + this.maxTags + ' тег.';
                return '';
            },

            addExisting(t) {
                const err = this.validateName(t.name);
                if (err) { this.error = err; return; }
                this.selected.push({ slug: t.slug, name: t.name, status: 'accepted' });
                this.inputValue = '';
                this.suggestions = [];
                this.showSuggestions = false;
                this.highlightIndex = -1;
                this.$refs.input.focus();
            },

            addCurrent() {
                if (this.highlightIndex >= 0 && this.suggestions[this.highlightIndex]) {
                    this.addExisting(this.suggestions[this.highlightIndex]);
                    return;
                }
                const raw = this.inputValue.trim();
                if (!raw) return;
                const err = this.validateName(raw);
                if (err) { this.error = err; return; }
                const exact = accepted.find(t =>
                    t.name.toLowerCase() === raw.toLowerCase() ||
                    t.slug.toLowerCase() === raw.toLowerCase()
                );
                if (exact) { this.addExisting(exact); return; }
                /* Новый тег: backend создаст Tag(status=pending) после submit */
                this.selected.push({ slug: '', name: raw, status: 'new' });
                this.inputValue = '';
                this.suggestions = [];
                this.showSuggestions = false;
            },

            onBackspace() {
                if (this.inputValue === '' && this.selected.length > 0) {
                    this.selected.pop();
                    this.error = '';
                }
            },

            remove(idx) {
                this.selected.splice(idx, 1);
                this.error = '';
            }
        };
    });
});
