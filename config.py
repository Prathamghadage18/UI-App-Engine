from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    DB_PORT: str

    INFLUX_BASE_URL: str
    INFLUX_DB: str
    INFLUX_USER: str
    INFLUX_PASSWORD: str

    class Config:
        env_file = ".env"

    @property
    def POSTGRES_URL(self):
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


settings = Settings()