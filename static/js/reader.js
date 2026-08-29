/* storyReader — Alpine-компонент страницы произведения (FR-STORY-07).
 *
 * Держит три оси настроек чтения, состояние двух bottom-sheet'ов и режим
 * чтения.
 *
 *  1. Настройки переживают переход к следующей главе. Навигация по главам —
 *     это full reload на ?chapter=N, поэтому значения читаются из
 *     localStorage и валидируются по белому списку: чужое или устаревшее
 *     значение падает в fallback, а не уезжает классом в разметку.
 *  2. Панели чтения нужен IntersectionObserver и обработчик скролла, а это
 *     уже не выражается атрибутом.
 *
 * Файл подключается блоком `page_scripts` — то есть с `defer` и ДО
 * alpine.min.js: `defer` исполняет в порядке документа, и слушатель
 * `alpine:init` обязан встать раньше старта Alpine.
 */
(function () {
    var AXES = {
        size:  { key: 'bp-reader-size',  values: ['reader-size-base', 'reader-size-large'],                          fallback: 'reader-size-base' },
        lead:  { key: 'bp-reader-lead',  values: ['reader-lead-tight', 'reader-lead-airy'],                          fallback: 'reader-lead-airy' },
        theme: { key: 'bp-reader-theme', values: ['reader-theme-paper', 'reader-theme-warm', 'reader-theme-night'],  fallback: 'reader-theme-paper' }
    };

    function load(axis) {
        try {
            var stored = window.localStorage.getItem(AXES[axis].key);
            return AXES[axis].values.indexOf(stored) > -1 ? stored : AXES[axis].fallback;
        } catch (e) {
            return AXES[axis].fallback;   /* приватный режим — просто не запоминаем */
        }
    }

    function save(axis, value) {
        try { window.localStorage.setItem(AXES[axis].key, value); } catch (e) {}
    }

    document.addEventListener('alpine:init', function () {
        Alpine.data('storyReader', function () {
            return {
                readerSize:   load('size'),
                readerLead:   load('lead'),
                readerTheme:  load('theme'),
                settingsOpen: false,
                chaptersOpen: false,
                reading:      false,
                progress:     0,

                init: function () {
                    var self = this;
                    this.$watch('readerSize',  function (v) { save('size',  v); });
                    this.$watch('readerLead',  function (v) { save('lead',  v); });
                    this.$watch('readerTheme', function (v) { save('theme', v); });

                    var body = this.$el.querySelector('[data-chapter-body]');
                    if (!body) return;

                    if ('IntersectionObserver' in window) {
                        new IntersectionObserver(function (entries) {
                            self.setReading(entries[0].isIntersecting);
                        }, { rootMargin: '-72px 0px -96px 0px' }).observe(body);
                    }

                    var track = function () { self.track(body); };
                    window.addEventListener('scroll', track, { passive: true });
                    window.addEventListener('resize', track, { passive: true });
                    track();
                },

                /* Панель чтения занимает место нижнего меню, поэтому о входе
                 * в режим чтения нужно сообщить наружу — mobile_nav слушает
                 * это событие и убирает свою пилюлю (docs/ui.md). */
                setReading: function (on) {
                    if (this.reading === on) return;
                    this.reading = on;
                    window.dispatchEvent(new CustomEvent('reading-mode', { detail: { on: on } }));
                },

                track: function (body) {
                    var rect = body.getBoundingClientRect();
                    var viewport = window.innerHeight || document.documentElement.clientHeight;
                    var scrollable = rect.height - viewport;
                    var done = scrollable > 0
                        ? -rect.top / scrollable
                        : (rect.bottom <= viewport ? 1 : 0);
                    this.progress = Math.max(0, Math.min(100, Math.round(done * 100)));
                }
            };
        });
    });
})();
