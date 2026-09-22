from chatbot import main


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye.")
    except EOFError:
        print("\nNo interactive input detected. Run the chatbot in a real terminal window to chat.")
