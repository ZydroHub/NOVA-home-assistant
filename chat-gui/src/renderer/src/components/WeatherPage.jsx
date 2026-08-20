import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
    AlertCircle,
    Cloud,
    CloudFog,
    CloudRain,
    CloudSnow,
    CloudSun,
    Loader2,
    MapPin,
    SunMedium,
    Sunrise,
    Sunset,
    Thermometer,
    Umbrella,
    Wind,
} from 'lucide-react';
import { pageEntrance, panelEntrance } from '../motionPresets.js';
import { fetchLatestWeather, getWeatherCache, isCacheFresh, WEATHER_REFRESH_MS } from '../integrationCache.js';

const CITY_LABEL = 'Stockholm';

function formatNumber(value, fallback = null) {
    return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : fallback;
}

function formatDecimal(value, fallback = '--') {
    return typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 10) / 10 : fallback;
}

function formatTimePart(value) {
    if (!value) return '--:--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '--:--';
    return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
    });
}

function formatForecastDay(value) {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '--';
    return date.toLocaleDateString('en-US', { weekday: 'short' });
}

function formatTemperature(value, suffix = '°') {
    return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}${suffix}` : '--';
}

function getWeatherMeta(code) {
    if (code === 0) {
        return {
            label: 'Sunny',
            summary: 'Bright skies and clean visibility through most of the day.',
            icon: SunMedium,
        };
    }
    if (code === 1 || code === 2) {
        return {
            label: 'Partly cloudy',
            summary: 'Soft cloud cover with clear breaks and stable conditions.',
            icon: CloudSun,
        };
    }
    if (code === 3) {
        return {
            label: 'Cloudy',
            summary: 'Dense cloud cover overhead with a muted, even sky.',
            icon: Cloud,
        };
    }
    if (code === 45 || code === 48) {
        return {
            label: 'Fog',
            summary: 'Lower visibility and a cooler, hazy feel outside.',
            icon: CloudFog,
        };
    }
    if (code >= 51 && code <= 67) {
        return {
            label: 'Rain',
            summary: 'Moist air and active rainfall moving through the area.',
            icon: CloudRain,
        };
    }
    if (code >= 71 && code <= 77) {
        return {
            label: 'Snow',
            summary: 'Cold conditions with snow present in the system.',
            icon: CloudSnow,
        };
    }
    if (code >= 80 && code <= 82) {
        return {
            label: 'Showers',
            summary: 'Intermittent bursts of rain with changing sky texture.',
            icon: CloudRain,
        };
    }
    if (code >= 85 && code <= 86) {
        return {
            label: 'Snow showers',
            summary: 'Passing snow bands with a wintry edge in the air.',
            icon: CloudSnow,
        };
    }

    return {
        label: 'Mixed',
        summary: 'Conditions are shifting throughout the day.',
        icon: CloudSun,
    };
}

function getHeroGlow(code) {
    if (code === 0) {
        return 'radial-gradient(circle at 18% 18%, rgba(255, 199, 88, 0.30), transparent 34%), radial-gradient(circle at 86% 24%, rgba(102, 224, 255, 0.16), transparent 26%), linear-gradient(145deg, rgba(11,23,56,0.94), rgba(8,15,36,0.92) 48%, rgba(4,22,35,0.96))';
    }
    if (code === 3 || code === 45 || code === 48) {
        return 'radial-gradient(circle at 18% 18%, rgba(104, 195, 255, 0.18), transparent 34%), radial-gradient(circle at 86% 24%, rgba(124, 146, 255, 0.18), transparent 26%), linear-gradient(145deg, rgba(12,19,44,0.94), rgba(8,13,30,0.94) 48%, rgba(7,17,36,0.98))';
    }
    if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) {
        return 'radial-gradient(circle at 18% 18%, rgba(88, 193, 255, 0.24), transparent 34%), radial-gradient(circle at 86% 24%, rgba(53, 106, 255, 0.22), transparent 26%), linear-gradient(145deg, rgba(10,19,46,0.94), rgba(6,12,31,0.94) 48%, rgba(4,19,38,0.98))';
    }
    if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) {
        return 'radial-gradient(circle at 18% 18%, rgba(230, 245, 255, 0.20), transparent 34%), radial-gradient(circle at 86% 24%, rgba(154, 216, 255, 0.18), transparent 26%), linear-gradient(145deg, rgba(11,20,44,0.94), rgba(7,13,32,0.94) 48%, rgba(5,20,38,0.98))';
    }
    return 'radial-gradient(circle at 18% 18%, rgba(63, 213, 255, 0.22), transparent 34%), radial-gradient(circle at 86% 24%, rgba(60, 118, 255, 0.20), transparent 26%), linear-gradient(145deg, rgba(11,21,48,0.94), rgba(8,13,34,0.94) 48%, rgba(4,19,35,0.98))';
}

function GlassPanel({ title, subtitle, children, className = '', contentClassName = '' }) {
    return (
        <motion.section
            initial={{ opacity: 0, y: 10, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.22 }}
            className={`rounded-[22px] border border-cyan-200/12 bg-[linear-gradient(180deg,rgba(255,255,255,0.06),rgba(255,255,255,0.03))] p-3 shadow-[0_18px_50px_rgba(3,10,26,0.42)] backdrop-blur-xl transition-all duration-300 hover:border-cyan-200/18 hover:bg-[linear-gradient(180deg,rgba(255,255,255,0.07),rgba(255,255,255,0.035))] ${className}`}
        >
            <div className="flex items-end justify-between gap-4">
                <div>
                    <div className="text-[11px] uppercase tracking-[0.24em] text-cyan-100/48">{title}</div>
                    {subtitle ? <div className="mt-1 text-xs text-cyan-100/62">{subtitle}</div> : null}
                </div>
            </div>
            <div className={`${subtitle ? 'mt-3' : 'mt-2'} ${contentClassName}`}>{children}</div>
        </motion.section>
    );
}

export default function WeatherPage() {
    const [weather, setWeather] = useState(() => getWeatherCache()?.data || null);
    const [loading, setLoading] = useState(() => !getWeatherCache()?.data);
    const [error, setError] = useState('');

    useEffect(() => {
        let mounted = true;

        async function load({ force = false } = {}) {
            const cached = getWeatherCache();
            if (cached?.data) {
                setWeather(cached.data);
                setError('');
                setLoading(false);
            }

            if (!force && isCacheFresh(cached, WEATHER_REFRESH_MS)) return;

            if (!cached?.data) setLoading(true);

            try {
                const entry = await fetchLatestWeather();

                if (!mounted) return;

                setWeather(entry.data);
                setError('');
            } catch (err) {
                console.error('Weather fetch failed', err);
                if (mounted) {
                    const fallback = getWeatherCache();
                    if (fallback?.data) {
                        setWeather(fallback.data);
                        setError('');
                    } else {
                        setWeather(null);
                        setError(err?.message || 'Weather service temporarily unavailable');
                    }
                }
            } finally {
                if (mounted) setLoading(false);
            }
        }

        load();
        const timer = setInterval(() => load({ force: true }), WEATHER_REFRESH_MS);

        return () => {
            mounted = false;
            clearInterval(timer);
        };
    }, []);

    const current = weather?.current || {};
    const hourly = weather?.hourly || {};
    const daily = weather?.daily || {};

    const hourStartIndex = useMemo(() => {
        if (!Array.isArray(hourly.time) || hourly.time.length === 0) return 0;
        const currentTimeMs = current?.time ? Date.parse(current.time) : NaN;
        if (Number.isNaN(currentTimeMs)) return 0;

        const nextIndex = hourly.time.findIndex((entry) => {
            const entryMs = Date.parse(entry);
            return !Number.isNaN(entryMs) && entryMs >= currentTimeMs;
        });

        return nextIndex >= 0 ? nextIndex : 0;
    }, [current?.time, hourly.time]);

    const meta = getWeatherMeta(current.weather_code);
    const CurrentIcon = meta.icon;

    const todayHours = useMemo(() => {
        if (!Array.isArray(hourly.time)) return [];

        return hourly.time.slice(hourStartIndex, hourStartIndex + 5).map((hour, offset) => {
            const index = hourStartIndex + offset;
            return {
                time: formatTimePart(hour),
                temp: formatNumber(hourly.temperature_2m?.[index], null),
                rain: formatNumber(hourly.precipitation_probability?.[index], 0),
                code: hourly.weather_code?.[index],
            };
        });
    }, [hourStartIndex, hourly.precipitation_probability, hourly.temperature_2m, hourly.time, hourly.weather_code]);

    const days = useMemo(() => {
        if (!Array.isArray(daily.time)) return [];

        return daily.time.slice(0, 7).map((day, index) => ({
            day,
            code: daily.weather_code?.[index],
            min: formatNumber(daily.temperature_2m_min?.[index], null),
            max: formatNumber(daily.temperature_2m_max?.[index], null),
            rain: formatNumber(daily.precipitation_probability_max?.[index], 0),
        }));
    }, [daily.precipitation_probability_max, daily.temperature_2m_max, daily.temperature_2m_min, daily.time, daily.weather_code]);

    const sunrise = daily?.sunrise?.[0] ? formatTimePart(daily.sunrise[0]) : '--:--';
    const sunset = daily?.sunset?.[0] ? formatTimePart(daily.sunset[0]) : '--:--';
    const rainChanceToday = formatNumber(daily?.precipitation_probability_max?.[0], 0);
    const wind = formatNumber(current.wind_speed_10m, null);
    const uv = formatDecimal(current.uv_index, '--');
    const feelsLike = formatNumber(current.apparent_temperature, null);
    const temp = formatNumber(current.temperature_2m, null);
    const summaryLine = rainChanceToday !== null ? `Chance of rain: ${rainChanceToday}%` : meta.label;

    return (
        <motion.div
            className="h-full w-full min-h-0 overflow-hidden p-3 text-[#e9fbff]"
            variants={pageEntrance}
            initial="hidden"
            animate="visible"
            exit="exit"
        >
            <motion.section
                className="mx-auto flex h-full w-full max-w-7xl flex-col gap-3 rounded-[24px] border border-cyan-200/12 p-3 shadow-[0_18px_56px_rgba(2,10,28,0.5)]"
                variants={panelEntrance}
                style={{
                    background: 'linear-gradient(180deg, rgba(8, 14, 30, 0.92), rgba(7, 12, 26, 0.86))',
                    backdropFilter: 'blur(20px)',
                    WebkitBackdropFilter: 'blur(20px)',
                }}
            >
                <div className="flex flex-shrink-0 items-center justify-between gap-3">
                    <h2 className="nova-title text-3xl leading-none md:text-[2rem]">Weather</h2>

                    <div className="inline-flex items-center gap-2 rounded-full border border-cyan-200/15 bg-white/5 px-3 py-1 text-[11px] text-cyan-100/80">
                        <MapPin size={14} />
                        <span>{CITY_LABEL}</span>
                    </div>
                </div>

                {loading ? (
                    <div className="flex min-h-0 flex-1 items-center justify-center rounded-[24px] border border-cyan-200/10 bg-white/5">
                        <div className="flex items-center gap-3 text-cyan-100/70">
                            <Loader2 size={18} className="animate-spin" />
                            Loading weather...
                        </div>
                    </div>
                ) : error ? (
                    <div className="flex min-h-0 flex-1 items-center gap-3 rounded-[24px] border border-red-400/18 bg-red-500/10 px-6 text-red-100">
                        <AlertCircle size={18} />
                        <span>{error}</span>
                    </div>
                ) : (
                    <div className="weather-screen-grid">
                        <div className="weather-screen-main">
                            <motion.section
                                className="weather-screen-hero relative overflow-hidden rounded-[22px] border border-cyan-200/14 p-4 shadow-[0_24px_70px_rgba(2,10,28,0.48)]"
                                style={{ background: getHeroGlow(current.weather_code) }}
                                initial={{ opacity: 0, y: 14 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ duration: 0.35 }}
                            >
                                <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:34px_34px] opacity-30" />

                                <div className="relative grid grid-cols-[minmax(0,1fr)_126px] items-center gap-3">
                                    <div>
                                        <h3 className="text-xl font-semibold leading-none text-white md:text-2xl">{CITY_LABEL}</h3>
                                        <p className="mt-1 text-[11px] text-cyan-100/70 md:text-xs">{summaryLine}</p>

                                        <div className="mt-3 flex flex-wrap items-end gap-2">
                                            <div className="text-[56px] font-black leading-none tracking-[-0.04em] text-white md:text-[72px]">
                                                {temp !== null ? `${temp}°` : '--'}
                                            </div>
                                        </div>

                                        <div className="mt-3 flex flex-wrap gap-2">
                                            <div className="inline-flex items-center gap-1.5 rounded-full border border-cyan-200/12 bg-white/5 px-2.5 py-1 text-[10px] text-cyan-100/72">
                                                <Sunrise size={14} />
                                                Sunrise {sunrise}
                                            </div>
                                            <div className="inline-flex items-center gap-1.5 rounded-full border border-cyan-200/12 bg-white/5 px-2.5 py-1 text-[10px] text-cyan-100/72">
                                                <Sunset size={14} />
                                                Sunset {sunset}
                                            </div>
                                        </div>
                                    </div>

                                    <motion.div
                                        className="mx-auto flex h-[108px] w-[108px] items-center justify-center rounded-[20px] border border-cyan-200/14 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.18),transparent_35%),linear-gradient(160deg,rgba(255,255,255,0.08),rgba(255,255,255,0.03))] text-cyan-50 shadow-[0_20px_50px_rgba(0,0,0,0.24)]"
                                        animate={{ y: [0, -8, 0] }}
                                        transition={{ duration: 4.5, repeat: Infinity, ease: 'easeInOut' }}
                                    >
                                        <CurrentIcon size={62} strokeWidth={1.5} />
                                    </motion.div>
                                </div>
                            </motion.section>

                            <GlassPanel title="Today's Forecast" className="weather-screen-panel" contentClassName="weather-screen-panel-body">
                                {todayHours.length === 0 ? (
                                    <div className="rounded-[20px] border border-cyan-200/10 bg-white/5 px-5 py-6 text-center text-sm text-cyan-100/60">
                                        Hourly data unavailable.
                                    </div>
                                ) : (
                                    <div className="weather-screen-forecast-grid">
                                        {todayHours.map((slot, index) => {
                                            const slotMeta = getWeatherMeta(slot.code);
                                            const SlotIcon = slotMeta.icon;

                                            return (
                                                <motion.div
                                                    key={`${slot.time}-${index}`}
                                                    className="weather-screen-hour-card rounded-[16px] border border-cyan-200/10 bg-white/[0.045] px-2 py-2 text-center transition-all duration-300 hover:-translate-y-1 hover:border-cyan-200/18 hover:bg-white/[0.065]"
                                                    initial={{ opacity: 0, y: 10 }}
                                                    animate={{ opacity: 1, y: 0 }}
                                                    transition={{ duration: 0.2, delay: index * 0.04 }}
                                                >
                                                    <div className="text-[10px] uppercase tracking-[0.16em] text-cyan-100/50">{slot.time}</div>
                                                    <div className="mt-2.5 flex justify-center text-cyan-50">
                                                        <SlotIcon size={22} strokeWidth={1.7} />
                                                    </div>
                                                    <div className="mt-2 text-base font-semibold text-white">{formatTemperature(slot.temp)}</div>
                                                </motion.div>
                                            );
                                        })}
                                    </div>
                                )}
                            </GlassPanel>

                            <GlassPanel title="Air Conditions" className="weather-screen-panel" contentClassName="weather-screen-panel-body">
                                <div className="weather-screen-metrics-grid">
                                    {[
                                        {
                                            label: 'Real Feel',
                                            value: formatTemperature(feelsLike),
                                            icon: Thermometer,
                                        },
                                        {
                                            label: 'Wind Speed',
                                            value: wind !== null ? `${wind} km/h` : '--',
                                            icon: Wind,
                                        },
                                        {
                                            label: 'Rain Chance',
                                            value: `${rainChanceToday}%`,
                                            icon: Umbrella,
                                        },
                                        {
                                            label: 'UV Index',
                                            value: `${uv}`,
                                            icon: SunMedium,
                                        },
                                    ].map((metric) => {
                                        const Icon = metric.icon;

                                        return (
                                            <div
                                                key={metric.label}
                                                className="weather-screen-metric-card rounded-[16px] border border-cyan-200/10 bg-white/[0.045] px-2.5 py-2 transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-200/18 hover:bg-white/[0.065]"
                                            >
                                                <div className="flex min-w-0 items-center gap-2 text-cyan-100/58">
                                                    <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg border border-cyan-200/10 bg-cyan-300/[0.08] text-cyan-50">
                                                        <Icon size={14} />
                                                    </div>
                                                    <div className="truncate text-[9px] uppercase tracking-[0.12em]">{metric.label}</div>
                                                </div>
                                                <div className="mt-2 text-lg font-semibold leading-none text-white">{metric.value}</div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </GlassPanel>
                        </div>

                        <GlassPanel title="7-Day Forecast" className="weather-screen-panel weather-screen-seven-day" contentClassName="weather-screen-panel-body">
                            {days.length === 0 ? (
                                <div className="rounded-[20px] border border-cyan-200/10 bg-white/5 px-5 py-8 text-center text-sm text-cyan-100/60">
                                    Weather data unavailable.
                                </div>
                            ) : (
                                <div className="weather-screen-forecast-list">
                                    {days.map((item, index) => {
                                        const dayMeta = getWeatherMeta(item.code);
                                        const DayIcon = dayMeta.icon;

                                        return (
                                            <motion.div
                                                key={`${item.day}-${index}`}
                                                className="weather-screen-day-row grid min-h-0 grid-cols-[34px_28px_minmax(0,1fr)_auto] items-center gap-2 rounded-[16px] border border-cyan-200/10 bg-white/[0.045] px-3 py-1 transition-all duration-300 hover:border-cyan-200/18 hover:bg-white/[0.065]"
                                                initial={{ opacity: 0, x: 10 }}
                                                animate={{ opacity: 1, x: 0 }}
                                                transition={{ duration: 0.22, delay: index * 0.04 }}
                                            >
                                                <div className="text-[11px] font-semibold text-white">{formatForecastDay(item.day)}</div>
                                                <div className="flex justify-center text-cyan-50">
                                                    <DayIcon size={16} strokeWidth={1.7} />
                                                </div>
                                                <div className="min-w-0">
                                                    <div className="truncate text-[11px] font-medium text-cyan-50">{dayMeta.label}</div>
                                                </div>
                                                <div className="whitespace-nowrap text-[11px] text-cyan-100/70">
                                                    <span className="font-semibold text-white">{formatTemperature(item.max)}</span>
                                                    <span className="mx-1 text-cyan-100/40">/</span>
                                                    <span>{formatTemperature(item.min)}</span>
                                                </div>
                                            </motion.div>
                                        );
                                    })}
                                </div>
                            )}
                        </GlassPanel>
                    </div>
                )}
            </motion.section>
        </motion.div>
    );
}
