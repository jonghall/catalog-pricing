"""
MIT License

Copyright (c) 2024 Jon Hall

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

__author__ = 'jonhall'
import os, logging, logging.config, os.path, argparse, json
import pandas as pd
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_platform_services import GlobalCatalogV1


def setup_logging(default_path='logging.json', default_level=logging.info, env_key='LOG_CFG'):
    # read logging.json for log parameters to be ued by script
    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)
def createSDK(IC_API_KEY):
    """
    Create SDK clients
    """
    global global_catalog

    try:
        authenticator = IAMAuthenticator(IC_API_KEY)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit(1)

    try:
        global_catalog = GlobalCatalogV1(authenticator=authenticator)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit(1)

if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Pull raw metric prices from IBM Cloud global catalog..")
    parser.add_argument("--output", default=os.environ.get('output', 'prices.xlsx'), help="Filename Excel output file. (including extension of .xlsx)")
    parser.add_argument("--apikey", default=os.environ.get('apikey', None), help="IBM Cloud apikey to use.--")
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, help="Set Debug level for logging.")
    parser.add_argument("--service_id", help="Service ID to lookup", default="is.instance")
    parser.add_argument("--query", help="Query to filter", default=None)
    parser.add_argument("--location", help="Deployment location to query", default=None)
    parser.add_argument("--country", help="Consumption Country for pricing", default="USA")
    parser.add_argument("--currency", help="Currency for pricing", default="USD")

    args = parser.parse_args()
    output = args.output
    service_id = args.service_id
    query = args.query
    location = args.location
    country = args.country
    currency = args.currency
    data = []

    createSDK(args.apikey)

    """Search Catalog for service_id, filter based on query """
    entry_search_result = global_catalog.get_child_objects(
        id=service_id,
        kind="plan",
        q=query,
        offset=0,
        limit=100,
        complete=True).get_result()
    for p in entry_search_result["resources"]:
        plan_id = p["id"]
        plan_name = p["name"]
        """ Get Deployments Available """
        deployments = global_catalog.get_child_objects(
            id=plan_id,
            kind="deployment",
            offset=0,
            limit=100,
            complete=True).get_result()
        for d in deployments["resources"]:
            deployment_id = d["id"]
            deployment_name = d["name"]
            deployment_location = d["metadata"]["deployment"]["location"]
            """ get pricing for deployment"""
            if location is None or location == deployment_location:
                try:
                    pricing = global_catalog.get_pricing(
                      id=deployment_id,
                      origin="pricing_catalog",
                      type="paygo").get_result()
                except ApiException as e:
                    """ Error getting pricing"""
                    logging.error("Error: {}".format(str(e)))
                    pricing["metrics"] = []

                """ Parse metrics for deployment """
                for m in pricing["metrics"]:
                    metric_id = m["metric_id"]
                    tier_model = m["tier_model"]
                    charge_unit_name = m["charge_unit_name"]
                    if "charge_unit_quantity" in m["charge_unit_name"]:
                        charge_unit_qty = m["charge_unit_quantity"]
                    else:
                        charge_unit_qty = 0

                    if m["amounts"] != None:
                        for a in m["amounts"]:
                            if a["country"] == country and a["currency"] == currency:
                                """ parse pricing tiers """
                                for t in a["prices"]:
                                    quantity_tier = t["quantity_tier"]
                                    price = t["price"]
                                    logging.info("{} {} {} {} {} {} {} {} {} {} {}".format(service_id, plan_id, plan_name, deployment_id, deployment_name, deployment_location, metric_id, tier_model, charge_unit_name, charge_unit_qty, quantity_tier, price))
                                    row = {
                                        "servuce_id": service_id,
                                        "plan_id": plan_id,
                                        "plan_name": plan_name,
                                        "deployment_id": deployment_id,
                                        "deployment_name": deployment_name,
                                        "deployment_location": deployment_location,
                                        "metric_id": metric_id,
                                        "tier_model": tier_model,
                                        "charge_unit_name": charge_unit_name,
                                        "charge_unit_qty": int(charge_unit_qty),
                                        "quatity_tier": int(quantity_tier),
                                        "price":  float(price)
                                        }
                                    data.append(row.copy())
                    else:
                        logging.error("No price data for deployment_id {} metric {}".format(deployment_id, metric_id))
                        logging.error(m)

    """ create dataframe """
    if len(data) > 0:
        pricingDetail = pd.DataFrame(data, columns=list(data[0].keys()))

        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        workbook = writer.book
        pricingDetail.to_excel(writer, sheet_name="PricingDetail")
        worksheet = writer.sheets['PricingDetail']
        totalrows, totalcols = pricingDetail.shape
        worksheet.autofilter(0, 0, totalrows, totalcols)
        writer.close()