"""
Comparison Engine for BrandSafe - Side-by-side creator comparison and ranking.

Provides tools to compare multiple creators across various metrics, rank them,
and generate portfolio-level insights.
"""

import pandas as pd
from typing import List, Dict, Optional
from storage import DatabaseManager


class ComparisonEngine:
    """Engine for comparing multiple creators and generating comparative analytics"""

    def __init__(self, db: DatabaseManager):
        """
        Initialize comparison engine

        Args:
            db: DatabaseManager instance
        """
        self.db = db

    def compare_creators(self, creator_ids: List[int], brief_id: int) -> Dict:
        """
        Compare multiple creators side-by-side

        Args:
            creator_ids: List of creator IDs to compare
            brief_id: Brief ID for context

        Returns:
            Dict with structured comparison data
        """
        if not creator_ids:
            return {'error': 'No creators provided for comparison'}

        comparison_data = {
            'creators': [],
            'metrics_summary': {},
            'rankings': {}
        }

        for creator_id in creator_ids:
            creator_data = self._get_creator_comparison_data(creator_id, brief_id)
            if creator_data:
                comparison_data['creators'].append(creator_data)

        # Calculate rankings
        if comparison_data['creators']:
            comparison_data['rankings'] = self._calculate_rankings(comparison_data['creators'])

        # Calculate summary statistics
        comparison_data['metrics_summary'] = self._calculate_summary_metrics(comparison_data['creators'])

        return comparison_data

    def _get_creator_comparison_data(self, creator_id: int, brief_id: int) -> Optional[Dict]:
        """
        Get all relevant data for a single creator

        Args:
            creator_id: Creator ID
            brief_id: Brief ID

        Returns:
            Dict with creator data or None
        """
        # Get creator basic info
        creator = self.db.get_creator(creator_id)
        if not creator:
            return None

        # Get report
        report = self.db.get_creator_report(brief_id, creator_id)

        # Get social accounts
        social_accounts = self.db.get_social_accounts(creator_id)

        # Aggregate platform stats
        total_followers = 0
        total_posts = 0
        platforms = []
        engagement_rates = []

        for _, account in social_accounts.iterrows():
            platforms.append(account['platform'])

            # Get latest analytics
            analytics = self.db.get_latest_analytics(account['id'])
            if analytics:
                followers = analytics.get('followers_count', 0) or 0
                posts = analytics.get('total_posts', 0) or 0
                total_followers += followers
                total_posts += posts

                # Calculate engagement rate if we have post data
                posts_data = self.db.get_posts_for_account(account['id'], limit=10)
                if not posts_data.empty:
                    avg_engagement = (posts_data['likes_count'].mean() +
                                    posts_data['comments_count'].mean())
                    if followers > 0:
                        engagement_rate = (avg_engagement / followers) * 100
                        engagement_rates.append(engagement_rate)

        avg_engagement_rate = sum(engagement_rates) / len(engagement_rates) if engagement_rates else 0

        # Build comparison data
        overall_score = report.get('overall_score', 0) if report else 0
        natural_alignment_score = report.get('natural_alignment_score', 0) if report else 0

        data = {
            'id': creator_id,
            'name': creator['name'],
            'platforms': platforms,
            'platform_count': len(platforms),
            'total_followers': total_followers,
            'total_posts': total_posts,
            'avg_engagement_rate': avg_engagement_rate,
            'overall_score': overall_score,
            'natural_alignment_score': natural_alignment_score,
            'brand_safety_score': overall_score,  # TODO: Extract from content analysis
            'content_quality_score': overall_score,  # TODO: Extract from content analysis
            'audience_fit_score': overall_score,  # TODO: Extract from content analysis
            'engagement_quality_score': overall_score,  # TODO: Extract from content analysis
            'estimated_cost': 0,  # TODO: Add cost estimation logic
        }

        return data

    def _calculate_rankings(self, creators: List[Dict]) -> Dict:
        """
        Calculate rankings for each metric

        Args:
            creators: List of creator comparison data

        Returns:
            Dict with rankings
        """
        if not creators:
            return {}

        df = pd.DataFrame(creators)

        rankings = {
            'overall_score': self._rank_column(df, 'overall_score', ascending=False),
            'natural_alignment_score': self._rank_column(df, 'natural_alignment_score', ascending=False),
            'total_followers': self._rank_column(df, 'total_followers', ascending=False),
            'avg_engagement_rate': self._rank_column(df, 'avg_engagement_rate', ascending=False),
            'brand_safety_score': self._rank_column(df, 'brand_safety_score', ascending=False),
            'cost_per_follower': self._rank_cost_efficiency(df)
        }

        return rankings

    def _rank_column(self, df: pd.DataFrame, column: str, ascending: bool = False) -> List[Dict]:
        """Rank creators by a specific column"""
        if column not in df.columns:
            return []

        ranked = df.sort_values(column, ascending=ascending)
        return [
            {
                'rank': idx + 1,
                'creator_id': row['id'],
                'name': row['name'],
                'value': row[column]
            }
            for idx, (_, row) in enumerate(ranked.iterrows())
        ]

    def _rank_cost_efficiency(self, df: pd.DataFrame) -> List[Dict]:
        """Rank creators by cost per follower"""
        df['cost_per_follower'] = df.apply(
            lambda row: row['estimated_cost'] / row['total_followers']
            if row['total_followers'] > 0 else float('inf'),
            axis=1
        )

        ranked = df.sort_values('cost_per_follower', ascending=True)
        return [
            {
                'rank': idx + 1,
                'creator_id': row['id'],
                'name': row['name'],
                'value': row['cost_per_follower'] if row['cost_per_follower'] != float('inf') else 0
            }
            for idx, (_, row) in enumerate(ranked.iterrows())
        ]

    def _calculate_summary_metrics(self, creators: List[Dict]) -> Dict:
        """
        Calculate summary statistics across all creators

        Args:
            creators: List of creator comparison data

        Returns:
            Dict with summary metrics
        """
        if not creators:
            return {}

        df = pd.DataFrame(creators)

        summary = {
            'total_creators': len(creators),
            'total_reach': int(df['total_followers'].sum()),
            'avg_followers': int(df['total_followers'].mean()),
            'avg_engagement_rate': float(df['avg_engagement_rate'].mean()),
            'avg_overall_score': float(df['overall_score'].mean()),
            'avg_natural_alignment': float(df['natural_alignment_score'].mean()),
            'avg_brand_safety': float(df['brand_safety_score'].mean()),
            'total_estimated_cost': float(df['estimated_cost'].sum()),
            'platforms_covered': len(set([p for creator in creators for p in creator['platforms']])),
        }

        # Add quality distribution
        high_quality = len(df[df['overall_score'] >= 4.0])
        medium_quality = len(df[(df['overall_score'] >= 3.0) & (df['overall_score'] < 4.0)])
        low_quality = len(df[df['overall_score'] < 3.0])

        summary['quality_distribution'] = {
            'high': high_quality,
            'medium': medium_quality,
            'low': low_quality
        }

        return summary

    def rank_creators(self, brief_id: int, sort_by: str = "overall_score",
                     ascending: bool = False) -> pd.DataFrame:
        """
        Rank all creators for a brief by a specific metric

        Args:
            brief_id: Brief ID
            sort_by: Metric to sort by
            ascending: Sort order

        Returns:
            DataFrame with ranked creators
        """
        # Get all reports for brief
        reports = self.db.get_reports_for_brief(brief_id)

        if reports.empty:
            return pd.DataFrame()

        # Get detailed data for each creator
        creator_data = []
        for _, report in reports.iterrows():
            data = self._get_creator_comparison_data(report['creator_id'], brief_id)
            if data:
                creator_data.append(data)

        if not creator_data:
            return pd.DataFrame()

        df = pd.DataFrame(creator_data)

        # Sort by requested metric
        if sort_by in df.columns:
            df = df.sort_values(sort_by, ascending=ascending)

        # Add rank column
        df['rank'] = range(1, len(df) + 1)

        return df

    def generate_portfolio_summary(self, brief_id: int) -> Dict:
        """
        Generate portfolio-level analytics for a brief

        Args:
            brief_id: Brief ID

        Returns:
            Dict with portfolio summary
        """
        reports = self.db.get_reports_for_brief(brief_id)

        if reports.empty:
            return {'error': 'No reports found for this brief'}

        creator_ids = reports['creator_id'].tolist()
        comparison = self.compare_creators(creator_ids, brief_id)

        # Add portfolio-specific insights
        portfolio = {
            'summary': comparison['metrics_summary'],
            'top_performers': self._get_top_performers(comparison['creators']),
            'recommendations': self._generate_portfolio_recommendations(comparison),
            'risk_assessment': self._assess_portfolio_risk(comparison['creators'])
        }

        return portfolio

    def _get_top_performers(self, creators: List[Dict], top_n: int = 3) -> Dict:
        """Get top N performers across different metrics"""
        if not creators:
            return {}

        df = pd.DataFrame(creators)

        top_performers = {
            'by_score': df.nlargest(top_n, 'overall_score')[['name', 'overall_score']].to_dict('records'),
            'by_natural_alignment': df.nlargest(top_n, 'natural_alignment_score')[['name', 'natural_alignment_score']].to_dict('records'),
            'by_reach': df.nlargest(top_n, 'total_followers')[['name', 'total_followers']].to_dict('records'),
            'by_engagement': df.nlargest(top_n, 'avg_engagement_rate')[['name', 'avg_engagement_rate']].to_dict('records'),
        }

        return top_performers

    def _generate_portfolio_recommendations(self, comparison: Dict) -> List[str]:
        """Generate recommendations based on portfolio analysis"""
        recommendations = []
        creators = comparison['creators']
        summary = comparison['metrics_summary']

        if not creators:
            return recommendations

        # Check platform diversity
        if summary.get('platforms_covered', 0) < 3:
            recommendations.append("Consider adding creators from more platforms for better reach diversity")

        # Check quality distribution
        quality_dist = summary.get('quality_distribution', {})
        low_quality_pct = (quality_dist.get('low', 0) / summary['total_creators']) * 100
        if low_quality_pct > 30:
            recommendations.append(f"⚠️ {low_quality_pct:.0f}% of creators have low brand fit scores (<3.0)")

        # Check cost efficiency
        if summary.get('total_estimated_cost', 0) > 100:
            recommendations.append("Consider prioritizing creators with better cost per follower ratios")

        # Check engagement
        if summary.get('avg_engagement_rate', 0) < 2:
            recommendations.append("Portfolio has low average engagement rate - focus on more engaging creators")

        # Positive feedback
        if summary.get('avg_overall_score', 0) >= 4:
            recommendations.append("✅ Strong portfolio with high average brand fit score")

        return recommendations

    def _assess_portfolio_risk(self, creators: List[Dict]) -> Dict:
        """Assess risk factors in the portfolio"""
        if not creators:
            return {}

        df = pd.DataFrame(creators)

        # Count creators below safety threshold
        unsafe_count = len(df[df['brand_safety_score'] < 3.0])

        # Check for concentration risk (too much reach from one creator)
        if not df.empty and len(df) > 1:
            max_follower_pct = (df['total_followers'].max() / df['total_followers'].sum()) * 100
        else:
            max_follower_pct = 100

        risk = {
            'unsafe_creators': unsafe_count,
            'concentration_risk': 'High' if max_follower_pct > 50 else 'Low',
            'max_creator_reach_pct': max_follower_pct,
            'overall_risk': 'High' if unsafe_count > 0 or max_follower_pct > 50 else 'Low'
        }

        return risk

    def estimate_campaign_roi(self, creator_ids: List[int], campaign_budget: float,
                             revenue_per_conversion: float, brief_id: int) -> Dict:
        """
        Estimate campaign ROI using realistic social media metrics

        Args:
            creator_ids: List of creator IDs
            campaign_budget: Total campaign budget
            revenue_per_conversion: Expected revenue per conversion
            brief_id: Brief ID

        Returns:
            Dict with ROI estimates

        Assumptions:
            - 3 posts per creator
            - 10% organic reach per post (typical for social media)
            - Engagement rate applied to reached users
            - 0.1% conversion rate from engaged users (realistic for e-commerce)
        """
        comparison = self.compare_creators(creator_ids, brief_id)

        if 'error' in comparison:
            return comparison

        summary = comparison['metrics_summary']

        # Get metrics
        total_followers = summary.get('total_reach', 0)
        avg_engagement_rate = summary.get('avg_engagement_rate', 0)
        num_creators = summary.get('total_creators', 1)

        # Realistic social media metrics
        posts_per_creator = 3
        organic_reach_rate = 0.10  # 10% of followers see each post
        conversion_rate = 0.001  # 0.1% of engagements convert

        # Calculate estimated metrics
        # Impressions = followers × reach rate × posts per creator
        estimated_impressions = total_followers * organic_reach_rate * posts_per_creator

        # Engagement = impressions × engagement rate
        # Note: avg_engagement_rate is already a percentage
        estimated_engagement = estimated_impressions * (avg_engagement_rate / 100)

        # Conversions = engagements × conversion rate
        estimated_conversions = estimated_engagement * conversion_rate

        # Revenue and ROI
        estimated_revenue = estimated_conversions * revenue_per_conversion
        roi_percentage = ((estimated_revenue - campaign_budget) / campaign_budget) * 100 if campaign_budget > 0 else 0

        roi_data = {
            'total_reach': total_followers,
            'estimated_impressions': int(estimated_impressions),
            'estimated_engagement': int(estimated_engagement),
            'estimated_conversions': int(estimated_conversions),
            'estimated_revenue': estimated_revenue,
            'campaign_budget': campaign_budget,
            'roi_percentage': roi_percentage,
            'cost_per_impression': campaign_budget / estimated_impressions if estimated_impressions > 0 else 0,
            'cost_per_engagement': campaign_budget / estimated_engagement if estimated_engagement > 0 else 0,
            'organic_reach_rate': organic_reach_rate * 100,
            'conversion_rate': conversion_rate * 100,
        }

        return roi_data
