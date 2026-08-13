import { useMemo, useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  Filler,
} from 'chart.js';
import { Line, Bar, Doughnut } from 'react-chartjs-2';
import { useTheme } from '../contexts/ThemeContext';
import { Card, cx } from './ui/primitives';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  Filler
);

/**
 * Chart.js takes concrete colour strings, not CSS variables, so the tokens are
 * resolved from the document at render time. Keyed on the active theme, the
 * charts re-resolve when the palette swaps rather than baking in one theme.
 */
function readToken(name, alpha = 1) {
  if (typeof window === 'undefined') return '#000';
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim();
  if (!raw) return '#000';
  return alpha === 1 ? `rgb(${raw})` : `rgba(${raw.split(' ').join(', ')}, ${alpha})`;
}

const VIEWS = [
  { id: 'line', label: 'Trend' },
  { id: 'bar', label: 'Volume' },
  { id: 'doughnut', label: 'Mix' },
];

export default function ActivityChart({ monthlySummaries = {}, recentActivity = [] }) {
  const [chartType, setChartType] = useState('line');
  const { theme } = useTheme();

  const months = Object.keys(monthlySummaries).sort();
  const counts = months.map((month) => monthlySummaries[month]);

  const palette = useMemo(
    () => ({
      accent: readToken('accent'),
      accentFill: readToken('accent', 0.12),
      ink: readToken('ink'),
      inkFaint: readToken('ink-faint'),
      line: readToken('border'),
      surface: readToken('surface'),
      // The stage pastels are this system's categorical set — they exist to
      // mark kinds of things, which is exactly what the mix chart shows.
      stages: [1, 2, 3, 4, 5].map((n) => readToken(`stage-${n}`)),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme]
  );

  const monthLabel = (m, opts) => {
    const [year, month] = m.split('-');
    return new Date(year, month - 1).toLocaleDateString('en-US', opts);
  };

  const lineChartData = {
    labels: months.map((m) => monthLabel(m, { month: 'short', year: 'numeric' })),
    datasets: [
      {
        label: 'Papers summarised',
        data: counts,
        borderColor: palette.accent,
        backgroundColor: palette.accentFill,
        pointBackgroundColor: palette.accent,
        pointBorderColor: palette.surface,
        pointBorderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        borderWidth: 2,
        tension: 0.35,
        fill: true,
      },
    ],
  };

  const barChartData = {
    labels: months.map((m) => monthLabel(m, { month: 'short' })),
    datasets: [
      {
        label: 'Papers per month',
        data: counts,
        backgroundColor: palette.accent,
        borderRadius: 4,
        borderWidth: 0,
        maxBarThickness: 28,
      },
    ],
  };

  const activityTypes = {};
  recentActivity.forEach((activity) => {
    const type = activity.activity_type || 'other';
    activityTypes[type] = (activityTypes[type] || 0) + 1;
  });

  const doughnutData = {
    labels: Object.keys(activityTypes).map(
      (t) => t.charAt(0).toUpperCase() + t.slice(1)
    ),
    datasets: [
      {
        data: Object.values(activityTypes),
        backgroundColor: palette.stages,
        borderColor: palette.surface,
        borderWidth: 2,
      },
    ],
  };

  const font = {
    family: "'JetBrains Mono Variable', ui-monospace, monospace",
    size: 11,
  };

  const tooltip = {
    backgroundColor: palette.ink,
    titleFont: { ...font, size: 12 },
    bodyFont: font,
    padding: 10,
    cornerRadius: 8,
    displayColors: false,
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    // Cursor's motion budget is tight; charts arrive quickly and settle.
    animation: { duration: 200, easing: 'easeOutQuart' },
    plugins: {
      legend: { display: false },
      title: { display: false },
      tooltip,
    },
    scales: {
      y: {
        beginAtZero: true,
        border: { display: false },
        ticks: { color: palette.inkFaint, font, stepSize: 1, padding: 8 },
        grid: { color: palette.line, drawTicks: false },
      },
      x: {
        border: { color: palette.line },
        ticks: { color: palette.inkFaint, font, padding: 8 },
        grid: { display: false },
      },
    },
  };

  const doughnutOptions = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '62%',
    animation: { duration: 200, easing: 'easeOutQuart' },
    plugins: {
      legend: {
        position: 'right',
        labels: {
          color: palette.inkFaint,
          font,
          padding: 14,
          boxWidth: 8,
          boxHeight: 8,
          usePointStyle: true,
          pointStyle: 'circle',
        },
      },
      title: { display: false },
      tooltip,
    },
  };

  const isEmpty = months.length === 0 && recentActivity.length === 0;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <h3 className="text-base font-semibold text-ink">Activity</h3>
        <div className="inline-flex rounded border border-line bg-surface-sunk p-0.5">
          {VIEWS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setChartType(id)}
              aria-pressed={chartType === id}
              className={cx(
                'rounded-sm px-3 py-1.5 text-caption font-medium',
                'transition-colors duration-fast ease-out',
                chartType === id
                  ? 'bg-surface text-ink'
                  : 'text-ink-faint hover:text-ink'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-64 p-6 md:h-72">
        {isEmpty ? (
          <div className="flex h-full items-center justify-center text-sm text-ink-faint">
            Nothing to plot yet. Summarise a paper to start the record.
          </div>
        ) : chartType === 'line' ? (
          <Line data={lineChartData} options={chartOptions} />
        ) : chartType === 'bar' ? (
          <Bar data={barChartData} options={chartOptions} />
        ) : (
          <Doughnut data={doughnutData} options={doughnutOptions} />
        )}
      </div>
    </Card>
  );
}
