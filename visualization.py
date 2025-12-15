"""
Visualization module for creating interactive charts and graphs for BrandSafe reports.

Uses Plotly for interactive visualizations that can be embedded in HTML reports
or exported as static images for PDF reports.
"""

import plotly.graph_objects as go
import plotly.express as px
from typing import List, Dict, Optional
import pandas as pd
from datetime import datetime


class ReportVisualizer:
    """Create interactive visualizations for creator analysis reports"""

    def __init__(self, theme: str = "plotly_white"):
        """
        Initialize visualizer with color theme

        Args:
            theme: Plotly template name (plotly, plotly_white, plotly_dark, etc.)
        """
        self.theme = theme
        self.brand_colors = {
            'primary': '#2E86AB',
            'success': '#06D6A0',
            'warning': '#F77F00',
            'danger': '#EF476F',
            'info': '#118AB2'
        }

    def create_engagement_trend_chart(self, posts: List[Dict]) -> go.Figure:
        """
        Create line chart showing engagement rate over time

        Args:
            posts: List of post dictionaries with date and engagement data

        Returns:
            Plotly Figure object
        """
        if not posts:
            return self._create_empty_figure("No posts data available")

        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(posts)

        # Ensure we have required columns
        if 'post_date' not in df.columns or 'likes_count' not in df.columns:
            return self._create_empty_figure("Missing required engagement data")

        # Convert dates
        df['post_date'] = pd.to_datetime(df['post_date'])
        df = df.sort_values('post_date')

        # Calculate engagement rate (likes + comments per post)
        df['engagement'] = df.get('likes_count', 0) + df.get('comments_count', 0)

        # Create line chart
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df['post_date'],
            y=df['engagement'],
            mode='lines+markers',
            name='Engagement',
            line=dict(color=self.brand_colors['primary'], width=2),
            marker=dict(size=6),
            hovertemplate='<b>%{x|%b %d, %Y}</b><br>' +
                         'Engagement: %{y:,.0f}<br>' +
                         '<extra></extra>'
        ))

        # Add trend line
        if len(df) > 2:
            z = np.polyfit(range(len(df)), df['engagement'], 1)
            p = np.poly1d(z)
            fig.add_trace(go.Scatter(
                x=df['post_date'],
                y=p(range(len(df))),
                mode='lines',
                name='Trend',
                line=dict(color=self.brand_colors['info'], width=2, dash='dash'),
                hoverinfo='skip'
            ))

        fig.update_layout(
            title='Engagement Over Time',
            xaxis_title='Date',
            yaxis_title='Total Engagement (Likes + Comments)',
            template=self.theme,
            hovermode='x unified',
            showlegend=True
        )

        return fig

    def create_sentiment_pie_chart(self, sentiment_data: Dict) -> go.Figure:
        """
        Create pie chart showing sentiment distribution

        Args:
            sentiment_data: Dict with sentiment categories and counts
                           e.g., {'positive': 45, 'neutral': 30, 'negative': 25}

        Returns:
            Plotly Figure object
        """
        if not sentiment_data:
            return self._create_empty_figure("No sentiment data available")

        labels = list(sentiment_data.keys())
        values = list(sentiment_data.values())

        colors = {
            'positive': self.brand_colors['success'],
            'neutral': '#A5A5A5',
            'negative': self.brand_colors['danger'],
            'mixed': self.brand_colors['warning']
        }

        pie_colors = [colors.get(label.lower(), self.brand_colors['info']) for label in labels]

        fig = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=pie_colors),
            hovertemplate='<b>%{label}</b><br>' +
                         'Count: %{value}<br>' +
                         'Percentage: %{percent}<br>' +
                         '<extra></extra>',
            textinfo='label+percent',
            textposition='auto'
        )])

        fig.update_layout(
            title='Sentiment Distribution',
            template=self.theme,
            showlegend=True
        )

        return fig

    def create_brand_safety_radar(self, scores: Dict) -> go.Figure:
        """
        Create radar/spider chart for brand safety dimensions

        Args:
            scores: Dict with dimension names and scores (1-5 scale)
                   e.g., {'Appropriateness': 4.5, 'Professionalism': 4.0, ...}

        Returns:
            Plotly Figure object
        """
        if not scores:
            return self._create_empty_figure("No brand safety scores available")

        categories = list(scores.keys())
        values = list(scores.values())

        # Close the radar chart
        categories_closed = categories + [categories[0]]
        values_closed = values + [values[0]]

        fig = go.Figure()

        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill='toself',
            fillcolor=f'rgba(46, 134, 171, 0.3)',
            line=dict(color=self.brand_colors['primary'], width=2),
            name='Brand Safety Score',
            hovertemplate='<b>%{theta}</b><br>' +
                         'Score: %{r:.1f}/5<br>' +
                         '<extra></extra>'
        ))

        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 5],
                    tickmode='linear',
                    tick0=0,
                    dtick=1
                )
            ),
            title='Brand Safety Scores',
            template=self.theme,
            showlegend=False
        )

        return fig

    def create_platform_comparison_bar(self, platform_data: Dict) -> go.Figure:
        """
        Create bar chart comparing metrics across platforms

        Args:
            platform_data: Dict with platform names as keys and metrics dict as values
                          e.g., {'youtube': {'followers': 10000, 'engagement': 500}, ...}

        Returns:
            Plotly Figure object
        """
        if not platform_data:
            return self._create_empty_figure("No platform data available")

        platforms = list(platform_data.keys())

        # Extract metrics (assuming all platforms have same metrics)
        metrics = {}
        for platform, data in platform_data.items():
            for metric, value in data.items():
                if metric not in metrics:
                    metrics[metric] = []
                metrics[metric].append(value)

        fig = go.Figure()

        colors = [self.brand_colors['primary'], self.brand_colors['success'],
                 self.brand_colors['warning'], self.brand_colors['info']]

        for idx, (metric, values) in enumerate(metrics.items()):
            fig.add_trace(go.Bar(
                name=metric.replace('_', ' ').title(),
                x=platforms,
                y=values,
                marker_color=colors[idx % len(colors)],
                hovertemplate='<b>%{x}</b><br>' +
                             f'{metric.replace("_", " ").title()}: %{{y:,.0f}}<br>' +
                             '<extra></extra>'
            ))

        fig.update_layout(
            title='Platform Comparison',
            xaxis_title='Platform',
            yaxis_title='Value',
            template=self.theme,
            barmode='group',
            hovermode='x unified'
        )

        return fig

    def create_creator_comparison_table(self, creators_data: List[Dict]) -> go.Figure:
        """
        Create comparison table for multiple creators

        Args:
            creators_data: List of creator dicts with metrics

        Returns:
            Plotly Figure object (table)
        """
        if not creators_data:
            return self._create_empty_figure("No creators to compare")

        # Extract metrics
        headers = ['Creator'] + list(creators_data[0].keys())

        cell_values = []
        for header in headers:
            if header == 'Creator':
                cell_values.append([c.get('name', 'Unknown') for c in creators_data])
            else:
                cell_values.append([c.get(header, 'N/A') for c in creators_data])

        fig = go.Figure(data=[go.Table(
            header=dict(
                values=[f'<b>{h}</b>' for h in headers],
                fill_color=self.brand_colors['primary'],
                font=dict(color='white', size=12),
                align='left'
            ),
            cells=dict(
                values=cell_values,
                fill_color=[['white', '#f0f0f0'] * len(creators_data)],
                align='left',
                font=dict(size=11)
            )
        )])

        fig.update_layout(
            title='Creator Comparison',
            template=self.theme,
            height=max(300, len(creators_data) * 50 + 100)
        )

        return fig

    def create_score_distribution_histogram(self, scores: List[float]) -> go.Figure:
        """
        Create histogram showing distribution of brand safety scores

        Args:
            scores: List of scores (1-5 scale)

        Returns:
            Plotly Figure object
        """
        if not scores:
            return self._create_empty_figure("No scores available")

        fig = go.Figure()

        fig.add_trace(go.Histogram(
            x=scores,
            nbinsx=10,
            marker_color=self.brand_colors['primary'],
            hovertemplate='Score Range: %{x}<br>' +
                         'Count: %{y}<br>' +
                         '<extra></extra>'
        ))

        # Add mean line
        mean_score = sum(scores) / len(scores) if scores else 0
        fig.add_vline(
            x=mean_score,
            line_dash="dash",
            line_color=self.brand_colors['success'],
            annotation_text=f"Mean: {mean_score:.2f}",
            annotation_position="top"
        )

        fig.update_layout(
            title='Score Distribution',
            xaxis_title='Brand Safety Score',
            yaxis_title='Number of Creators',
            template=self.theme,
            showlegend=False
        )

        return fig

    def create_portfolio_overview_cards(self, portfolio_stats: Dict) -> List[Dict]:
        """
        Create data for metric cards (to be rendered in Streamlit)

        Args:
            portfolio_stats: Dict with portfolio-level statistics

        Returns:
            List of dicts with card data
        """
        cards = []

        if 'total_reach' in portfolio_stats:
            cards.append({
                'title': 'Total Reach',
                'value': f"{portfolio_stats['total_reach']:,.0f}",
                'subtitle': 'Combined Followers',
                'color': self.brand_colors['primary']
            })

        if 'avg_score' in portfolio_stats:
            cards.append({
                'title': 'Average Score',
                'value': f"{portfolio_stats['avg_score']:.1f}/5",
                'subtitle': 'Brand Safety',
                'color': self.brand_colors['success']
            })

        if 'total_cost' in portfolio_stats:
            cards.append({
                'title': 'Est. Cost',
                'value': f"${portfolio_stats['total_cost']:.2f}",
                'subtitle': 'Analysis Cost',
                'color': self.brand_colors['info']
            })

        if 'platform_count' in portfolio_stats:
            cards.append({
                'title': 'Platforms',
                'value': str(portfolio_stats['platform_count']),
                'subtitle': 'Coverage',
                'color': self.brand_colors['warning']
            })

        return cards

    def _create_empty_figure(self, message: str) -> go.Figure:
        """Create empty figure with message"""
        fig = go.Figure()

        fig.add_annotation(
            text=message,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color='gray')
        )

        fig.update_layout(
            template=self.theme,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False)
        )

        return fig

    def export_to_html(self, fig: go.Figure, include_plotlyjs: str = 'cdn') -> str:
        """
        Export figure to HTML string

        Args:
            fig: Plotly figure
            include_plotlyjs: 'cdn', 'inline', or False

        Returns:
            HTML string
        """
        return fig.to_html(include_plotlyjs=include_plotlyjs, full_html=False)

    def export_to_image(self, fig: go.Figure, filepath: str,
                       width: int = 1200, height: int = 800, format: str = 'png'):
        """
        Export figure to static image (requires kaleido)

        Args:
            fig: Plotly figure
            filepath: Output file path
            width: Image width in pixels
            height: Image height in pixels
            format: 'png', 'jpg', 'svg', or 'pdf'
        """
        try:
            fig.write_image(filepath, width=width, height=height, format=format)
        except Exception as e:
            print(f"Warning: Could not export image. Install kaleido with: pip install kaleido")
            print(f"Error: {e}")


# Helper function to add numpy import if needed
try:
    import numpy as np
except ImportError:
    print("NumPy not installed. Trend lines will be disabled.")
    np = None
