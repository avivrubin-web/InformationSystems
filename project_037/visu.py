import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from utils import db_cur

# =========================
# 🎨 Global Design Settings
# =========================
sns.set_theme(
    style="white",
    context="talk",
    font="sans-serif"
)

plt.rcParams.update({
    "axes.titleweight": "bold",
    "axes.labelweight": "bold",
    "axes.titlesize": 20,
    "axes.labelsize": 14,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12,
})

# =========================
# 🔧 DB Helper
# =========================
def fetch_data(query):
    """Executes a SQL query and returns a DataFrame."""
    with db_cur() as cursor:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        data = cursor.fetchall()
    return pd.DataFrame(data, columns=columns)

# =========================
# 💰 Revenue Visualization
# =========================
def visualize_revenue():
    query = """
    SELECT manufacturer, airplane_size, seat_class, SUM(revenue) AS total_revenue
    FROM (
        SELECT a.manufacturer, a.airplane_size, 'Business' AS seat_class, r.business_class_cost AS revenue
        FROM reservations r
        JOIN flights f ON r.flight_id = f.flight_id
        JOIN airplanes a ON f.airplane_id = a.airplane_id
        WHERE r.business_class_cost > 0

        UNION ALL

        SELECT a.manufacturer, a.airplane_size, 'Economy' AS seat_class, r.economy_class_cost AS revenue
        FROM reservations r
        JOIN flights f ON r.flight_id = f.flight_id
        JOIN airplanes a ON f.airplane_id = a.airplane_id
        WHERE r.economy_class_cost > 0
    ) AS revenues
    GROUP BY manufacturer, airplane_size, seat_class
    ORDER BY manufacturer, airplane_size, seat_class;
    """

    df = fetch_data(query)

    if df.empty:
        print("No revenue data available.")
        return

    df["Manufacturer_Size"] = df["manufacturer"] + " (" + df["airplane_size"] + ")"

    plt.figure(figsize=(11, 6))

    palette = {
        "Business": "#1F3C88",  # כחול חזק
        "Economy": "#4FC3F7"    # תכלת
    }

    ax = sns.barplot(
        data=df,
        x="Manufacturer_Size",
        y="total_revenue",
        hue="seat_class",
        palette=palette
    )

    ax.set_title("Total Revenue by Airplane Type & Seat Class")
    ax.set_xlabel("Airplane Type")
    ax.set_ylabel("Total Revenue")

    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"${x:,.0f}")
    )

    ax.legend(title="Seat Class", frameon=False)

    sns.despine()
    plt.tight_layout()
    plt.show()

def visualize_cancellation_rate():
    query = """
    SELECT
        YEAR(reservation_date) AS year,
        MONTH(reservation_date) AS month,
        (SUM(CASE 
            WHEN reservation_status = 'cancelled_by_customer'
            THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
        ) AS cancellation_rate
    FROM reservations
    WHERE reservation_date IS NOT NULL
    GROUP BY
        YEAR(reservation_date),
        MONTH(reservation_date)
    HAVING COUNT(*) > 0
    ORDER BY
        year,
        month;
    """

    df = fetch_data(query)
    df["cancellation_rate"] = df["cancellation_rate"].astype(float)

    if df.empty:
        print("No cancellation data available.")
        return

    df["Year_Month"] = (
        df["year"].astype(str)
        + "-"
        + df["month"].astype(str).str.zfill(2)
    )

    plt.figure(figsize=(10, 5))

    ax = sns.lineplot(
        data=df,
        x="Year_Month",
        y="cancellation_rate",
        marker="o",
        linewidth=3,
        color="#1F3C88"
    )

    ax.set_title("Monthly Cancellation Rate")
    ax.set_xlabel("Month")
    ax.set_ylabel("Cancellation Rate (%)")

    ax.set_ylim(0, max(df["cancellation_rate"]) * 1.2)

    sns.despine()
    plt.tight_layout()
    plt.show()

# =========================
# ▶️ Run
# =========================
if __name__ == "__main__":
    print("Generating Revenue Visualization...")
    visualize_revenue()

    print("Generating Cancellation Rate Visualization...")
    visualize_cancellation_rate()

