# Cloudflare + SSL — راهنمای اپراتور

دامنه روی Cloudflare مدیریت می‌شود. این سند سه کار را پوشش می‌دهد:
TLS برای پنل Coolify، دامنه‌های اپ، و تنظیمات پیشنهادی Cloudflare.
**هیچ مقدار محرمانه‌ای اینجا یا در چت قرار نگیرد — فقط نام متغیرها (قانون ۴).**

## جای درست توکن Cloudflare

- اگر ورک‌فلویی به آن نیاز پیدا کرد → GitHub → Settings → Secrets → Actions →
  با نام `CLOUDFLARE_API_TOKEN`.
- اگر Coolify برای صدور گواهی DNS-challenge خواست → env همان resource در
  پنل Coolify با همین نام.
- Scope حداقلی بسازید: فقط Zone مربوطه، فقط `Zone → DNS → Edit`
  (برای WAF/Cache اگر لازم شد scope جدا). توکن Global API Key ندهید.
- توکن را هرگز در چت، کد، یا این ریپو نگذارید.

## ۱) TLS برای پنل Coolify (فوری — توکن دیپلوی الان روی HTTP می‌رود)

1. در Cloudflare یک رکورد `A` بسازید: `panel.rpim.ir` → IP سرور آمریکا،
   ابتدا **DNS-only (ابر خاکستری)**.
2. در پنل Coolify: Settings → Instance Domain را
   `https://panel.rpim.ir` بگذارید — Coolify خودش گواهی Let's Encrypt می‌گیرد
   (پورت 80/443 باید توسط پراکسی Coolify در دسترس باشد).
3. تست: `curl -I https://panel.rpim.ir` باید 200/302 با گواهی معتبر بدهد.
4. حالا در Cloudflare ابرِ رکورد را **نارنجی (Proxied)** کنید و در
   SSL/TLS → Overview حالت **Full (strict)** را بگذارید.
5. در GitHub → Settings → Variables → Actions مقدار
   `COOLIFY_URL=https://panel.rpim.ir` را ست کنید — ورک‌فلوها از همین متغیر
   می‌خوانند و دیگر به آدرس HTTP برنمی‌گردند.
6. **توکن COOLIFY_TOKEN را بچرخانید** (تا الان روی HTTP رفته): در Coolify
   توکن قبلی را باطل، توکن جدید least-privilege بسازید و Secret گیت‌هاب را
   به‌روز کنید.

## ۲) دامنه‌های اپ

| سرویس | رکورد پیشنهادی | کجا ست می‌شود |
|---|---|---|
| داشبورد | `app.rpim.ir` (Proxied) | Coolify → resource لگ ایران → Domains |
| core-api | `api.rpim.ir` (Proxied) | همان resource، سرویس core-api |

- گیت‌وی مدل (لگ آمریکا) دامنهٔ عمومی **نمی‌گیرد** — فقط داخلی است (قانون
  bind در ADR 0003/0025).
- بعد از ست کردن دامنه در Coolify، گواهی LE خودکار صادر می‌شود؛ بعد ابر
  نارنجی + Full (strict).
- `APP_BASE_URL` در env لگ ایران را با دامنهٔ نهایی داشبورد هماهنگ کنید.

## ۳) تنظیمات پیشنهادی Cloudflare (بعد از پایداری TLS)

- SSL/TLS: **Full (strict)** · Edge Certificates → Always Use HTTPS: on ·
  Minimum TLS: 1.2 · TLS 1.3: on.
- HSTS را فقط وقتی روشن کنید که مطمئنید همهٔ زیردامنه‌ها HTTPS پایدار دارند.
- Cache Rules: مسیرهای `api.rpim.ir/*` و `app.rpim.ir/api/*` → **Bypass cache**
  (API و صف تأیید نباید کش شوند)؛ استاتیک‌های Next.js (`/_next/static/*`) کش عادی.
- WAF: Managed Rules روشن؛ اگر چالش امنیتی روی `api.rpim.ir` مزاحم کلاینت‌ها
  شد، برای آن hostname قانون Skip بگذارید. Bot Fight Mode را روی API روشن نکنید.
- Firewall پیشنهادی: دسترسی `panel.rpim.ir` را با IP Access Rule به IPهای
  اپراتور + رنج GitHub Actions محدود کنید (job دیپلوی باید برسد) — یا پنل را
  DNS-only نگه دارید و به‌جای آن فایروال سرور را سفت کنید.

## چک‌لیست پایان

- [ ] `https://panel.rpim.ir` سبز و `COOLIFY_URL` متغیر ریپو ست شده
- [ ] `COOLIFY_TOKEN` چرخانده شد
- [ ] `app.rpim.ir` و `api.rpim.ir` پشت Cloudflare با Full (strict)
- [ ] Cache bypass روی مسیرهای API
- [ ] job دیپلوی CI بعد از تغییرها یک بار سبز اجرا شده
