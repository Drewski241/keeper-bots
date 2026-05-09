import asyncio

from your_api_file import CryptoComAccountAPI


async def main():

    api = CryptoComAccountAPI(
        api_key="YOUR_API_KEY",
        api_secret="YOUR_API_SECRET",
        sandbox=False,  # True for UAT
    )

    try:
        balances = await api.get_account_balance()

        print("\nSUCCESS\n")
        print(balances)

    except Exception as e:
        print("\nFAILED\n")
        print(e)

    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
