import { useEffect, useState } from 'react';
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
} from 'chart.js';
import { Line, Bar, Doughnut } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
);

export default function ActivityChart({ monthlySummaries = {}, recentActivity = [] }) {
  const [chartType, setChartType] = useState('line');

  // Prepare monthly data
  const months = Object.keys(monthlySummaries).sort();
  const counts = months.map(month => monthlySummaries[month]);

  const lineChartData = {
    labels: months.map(m => {
      const [year, month] = m.split('-');
      return new Date(year, month - 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }),
    datasets: [
      {
        label: 'Papers Summarized',
        data: counts,
        borderColor: 'rgb(20, 184, 166)',
        backgroundColor: 'rgba(20, 184, 166, 0.1)',
        tension: 0.4,
        fill: true,
      },
    ],
  };

  const barChartData = {
    labels: months.map(m => {
      const [year, month] = m.split('-');
      return new Date(year, month - 1).toLocaleDateString('en-US', { month: 'short' });
    }),
    datasets: [
      {
        label: 'Papers per Month',
        data: counts,
        backgroundColor: 'rgba(20, 184, 166, 0.8)',
        borderColor: 'rgb(20, 184, 166)',
        borderWidth: 1,
      },
    ],
  };

  // Activity type distribution
  const activityTypes = {};
  recentActivity.forEach(activity => {
    const type = activity.activity_type || 'other';
    activityTypes[type] = (activityTypes[type] || 0) + 1;
  });

  const doughnutData = {
    labels: Object.keys(activityTypes).map(t => t.charAt(0).toUpperCase() + t.slice(1)),
    datasets: [
      {
        data: Object.values(activityTypes),
        backgroundColor: [
          'rgba(20, 184, 166, 0.8)',
          'rgba(217, 119, 6, 0.8)',
          'rgba(239, 68, 68, 0.8)',
          'rgba(59, 130, 246, 0.8)',
          'rgba(168, 85, 247, 0.8)',
        ],
        borderColor: [
          'rgb(20, 184, 166)',
          'rgb(217, 119, 6)',
          'rgb(239, 68, 68)',
          'rgb(59, 130, 246)',
          'rgb(168, 85, 247)',
        ],
        borderWidth: 2,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: '#94a3b8',
          font: {
            family: "'Inter', sans-serif",
          },
        },
      },
      title: {
        display: false,
      },
    },
    scales: chartType !== 'doughnut' ? {
      y: {
        beginAtZero: true,
        ticks: {
          color: '#94a3b8',
          stepSize: 1,
        },
        grid: {
          color: 'rgba(148, 163, 184, 0.1)',
        },
      },
      x: {
        ticks: {
          color: '#94a3b8',
        },
        grid: {
          display: false,
        },
      },
    } : {},
  };

  const doughnutOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'right',
        labels: {
          color: '#94a3b8',
          font: {
            family: "'Inter', sans-serif",
          },
          padding: 15,
        },
      },
      title: {
        display: false,
      },
    },
  };

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-white">Activity Over Time</h3>
        <div className="flex gap-2">
          <button
            onClick={() => setChartType('line')}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              chartType === 'line'
                ? 'bg-teal-500 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            Line
          </button>
          <button
            onClick={() => setChartType('bar')}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              chartType === 'bar'
                ? 'bg-teal-500 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            Bar
          </button>
          <button
            onClick={() => setChartType('doughnut')}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              chartType === 'doughnut'
                ? 'bg-teal-500 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            Distribution
          </button>
        </div>
      </div>

      <div className="h-64 md:h-80">
        {months.length === 0 && recentActivity.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-400">
            No activity data available yet
          </div>
        ) : chartType === 'line' ? (
          <Line data={lineChartData} options={chartOptions} />
        ) : chartType === 'bar' ? (
          <Bar data={barChartData} options={chartOptions} />
        ) : (
          <Doughnut data={doughnutData} options={doughnutOptions} />
        )}
      </div>
    </div>
  );
}
